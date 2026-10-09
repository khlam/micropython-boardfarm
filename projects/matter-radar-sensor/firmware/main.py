"""Publish radar occupancy through Matter, with a hold a controller can set.

An HLK-LD2450 or HLK-LD2420 radar on UART1 and the board's status pixel make a
Matter Occupancy Sensor. A virtual Dimmable Light on the same node sets how long
occupancy holds after the room empties. Either radar works the same way.

Read this file top to bottom to audit the firmware: the board's pins, the
hardware main() creates, the two loops it runs and their states, then the
Occupancy object both loops update. Every output is chosen here:

- Matter occupancy on endpoint 1, and the pixel's product colour:
  Occupancy._show(), after every report, fault, and recovery.
- The pixel's Matter patterns, which outrank the product colour: StatusLed,
  fed by poll_matter().
- JSON lines over USB serial: each emit(), emit_state(), and error() call below.
"""

import asyncio
import os
import time
from collections import namedtuple

import machine
import neopixel
from hold import Hold, hold_ms
from micropython import const
from status import STATUS_LEVEL, product_color
from targets import TargetThrottle, outside_dead_zone

import matter
from matter.emit import emit, emit_state, error
from matter.status_led import StatusLed
from radar import NoRadarError, ReportStream, detect

# Pin map for this board, shared by every supported radar. ``tx`` connects to
# radar RX, ``rx`` to radar TX, and ``led_pin`` drives the onboard WS2812. Only
# ESP32-S3 is supported.
Board = namedtuple("Board", ("name", "uart_id", "tx", "rx", "led_pin"))
_machine = os.uname().machine
if "ESP32S3" not in _machine:
    raise RuntimeError(f"unsupported board: {_machine}")
BOARD = Board(name="ESP32-S3-Zero", uart_id=1, tx=5, rx=6, led_pin=21)

_MATTER_POLL_MS = const(50)
_RADAR_RETRY_MS = const(1_000)

# The links occupancy depends on. While either fails, the sensor reports
# occupied and the pixel shows yellow.
_MATTER = "matter"
_RADAR = "radar"


def main() -> None:
    """Create the hardware, start Matter, and run both loops forever."""
    pixel = neopixel.NeoPixel(machine.Pin(BOARD.led_pin, machine.Pin.OUT), 1)
    # Dim white until the first poll reports the Matter state.
    status_led = StatusLed(pixel, STATUS_LEVEL)

    node = matter.Node()
    # Endpoint IDs persist, so the occupancy sensor is always created first.
    sensor = node.create_endpoint(matter.EndpointType.OCCUPANCY_SENSOR)
    # A controller sets the hold with this light: off is none, full is ten minutes.
    hold_light = node.create_endpoint(matter.EndpointType.DIMMABLE_LIGHT)
    # Commissioning starts before the radar, so a missing radar never blocks
    # pairing. Blocks while ESP-Matter comes up, retrying its first reads every
    # 250 ms up to 40 times. A value in flash an endpoint's schema refuses
    # leaves that attribute at its default.
    for _rejected in node.start():
        error("python_validation", "restored value rejected by schema")
    emit({"event": "matter", "state": "ready"})
    emit({"event": "fabric", "state": node.state.fabric})

    # Occupied from boot until a radar report says otherwise.
    occupancy = Occupancy(sensor, hold_light, status_led)
    asyncio.run(_run(node, status_led, occupancy))


async def _run(node: matter.Node, status_led: StatusLed, occupancy: "Occupancy") -> None:
    """Run the Matter and radar loops together."""
    await asyncio.gather(poll_matter(node, status_led, occupancy), read_radar(occupancy))


async def poll_matter(node: matter.Node, status_led: StatusLed, occupancy: "Occupancy") -> None:
    """Poll Matter every 50 ms, stepping the pixel's blink on each pass.

    States:
        polling: each poll's device state goes to the pixel, each change of
            it goes out as JSON lines, and a failed pairing attempt flashes
            the pixel red.
        failing: occupancy holds occupied. The first failed poll is reported
            as ``matter_poll_err``, and the next good one as ``matter_ok``.

    Args:
        node: The started Matter node.
        status_led: The status pixel.
        occupancy: The room's occupancy, held occupied while polls fail.
    """
    failing = False
    while True:
        try:
            events = node.poll()
        except OSError as exception:
            occupancy.fault(_MATTER)
            if not failing:
                emit({"diag": "matter_poll_err", "err": str(exception)})
            failing = True
        else:
            for event in events:
                _report(event, status_led)
            if failing:
                emit({"diag": "matter_ok"})
                occupancy.recover(_MATTER)
            failing = False
            status_led.set_state(node.state)
        status_led.tick()
        await asyncio.sleep_ms(_MATTER_POLL_MS)


def _report(event: object, status_led: StatusLed) -> None:
    """Report one polled Matter event, flashing the pixel red on a failed pairing.

    The hold light's writes need nothing here: Occupancy reads its level at
    each report.

    Args:
        event: A change of Matter state, a controller write, or a controller
            value an endpoint's schema refused.
        status_led: The status pixel.
    """
    if isinstance(event, matter.StateEvent):
        emit_state(event)
        if event.failed:
            status_led.fail()
    elif isinstance(event, matter.RejectedValue):
        error("python_validation", "remote value rejected by schema")


async def read_radar(occupancy: "Occupancy") -> None:
    """Find the radar, read its reports, and find it again after any failure.

    States:
        finding: probe UART1 for an LD2450, then an LD2420. Success is
            reported as ``radar_ok``.
        reading: each report sets occupancy, then its targets go out as
            telemetry when due.
        failed: occupancy holds occupied, the first failure of a run is
            reported (``no_device``, ``init_err``, ``read_err``, or
            ``report_timeout``), the radar is closed, and finding starts again
            after a second.

    Args:
        occupancy: The room's occupancy, set by each report.
    """
    throttle = TargetThrottle()
    failing = False
    while True:
        radar = None
        try:
            model, radar = await detect(bus_id=BOARD.uart_id, tx=BOARD.tx, rx=BOARD.rx)
        except NoRadarError as exception:
            failure = {"diag": "no_device", "err": str(exception)}
        except OSError as exception:
            # detect() released every probe it opened.
            failure = {"diag": "init_err", "err": str(exception)}
        else:
            occupancy.recover(_RADAR)
            emit({"diag": "radar_ok", "model": model})
            failing = False
            failure = await _read_until_failure(radar, occupancy, throttle)

        occupancy.fault(_RADAR)
        if not failing:
            emit(failure)
        failing = True
        if radar is not None:
            _close(radar)
        await asyncio.sleep_ms(_RADAR_RETRY_MS)


async def _read_until_failure(
    radar: ReportStream, occupancy: "Occupancy", throttle: TargetThrottle
) -> dict:
    """Apply each report to occupancy, then send its targets when due.

    Targets in the dead zone around the sensor count for neither.

    Args:
        radar: The detected radar.
        occupancy: The room's occupancy, set by each report.
        throttle: Paces telemetry across every radar this loop finds.

    Returns:
        The diagnostic line for the failure that ended reading.
    """
    while True:
        try:
            targets = await radar.read_latest()
        except OSError as exception:
            return {"diag": "read_err", "err": str(exception)}
        now_ms = time.ticks_ms()
        if targets is None:
            return {"diag": "report_timeout", "t": now_ms}

        targets = tuple(target for target in targets if outside_dead_zone(target))
        occupancy.report(occupied=bool(targets), now_ms=now_ms)
        if throttle.due(targets, now_ms):
            emit(
                {
                    "t": now_ms,
                    "targets": [
                        {
                            "slot": target.slot,
                            "x_mm": target.x_mm,
                            "y_mm": target.y_mm,
                            "speed_cm_s": target.speed_cm_s,
                            "resolution_mm": target.resolution_mm,
                        }
                        for target in targets
                    ],
                }
            )


def _close(radar: ReportStream) -> None:
    """Release the radar's UART; a failure to close changes nothing."""
    try:  # noqa: SIM105 - contextlib is not available on MicroPython
        radar.close()
    except OSError:
        pass


class Occupancy:
    """Whether the room is occupied, and the two outputs that show it.

    Holds the hold state machine, the links that are failing, the occupancy
    sensor endpoint, the hold light whose level sets the hold, and the status
    pixel. Every change ends in :meth:`_show`.
    """

    def __init__(
        self, sensor: matter.Endpoint, hold_light: matter.Endpoint, status_led: StatusLed
    ) -> None:
        """Start occupied and show it, as the product requires during startup.

        Args:
            sensor: The Occupancy Sensor endpoint controllers read.
            hold_light: The Dimmable Light endpoint that sets the hold.
            status_led: The status pixel.
        """
        self._sensor = sensor
        self._hold_light = hold_light
        self._status_led = status_led
        self._hold = Hold()
        self._failing = set()
        self._published = None
        self._show()

    def report(self, *, occupied: bool, now_ms: int) -> None:
        """Apply one valid radar report; while a link fails, it counts as occupied.

        Args:
            occupied: Whether the report has a target outside the dead zone.
            now_ms: Monotonic time when the report was received.
        """
        self._hold.report(
            occupied=occupied or bool(self._failing),
            now_ms=now_ms,
            hold_ms=hold_ms(on=self._hold_light.on, level=self._hold_light.level),
        )
        self._show()

    def fault(self, link: str) -> None:
        """Hold occupied and discard any hold timer while ``link`` fails."""
        self._failing.add(link)
        self._hold.force_occupied()
        self._show()

    def recover(self, link: str) -> None:
        """Count ``link`` healthy again; the next report decides occupancy."""
        self._failing.discard(link)
        self._show()

    def _show(self) -> None:
        """Set the pixel's product colour, then publish occupancy if it changed.

        A failed publish leaves the Python endpoint holding the requested value
        while ESP-Matter holds the previous one, so this forgets what was
        published and the next call publishes whatever the state is then.
        """
        occupied = self._hold.occupied
        healthy = not self._failing
        self._status_led.set_application(product_color(healthy=healthy, occupied=occupied))
        if occupied == self._published:
            return
        try:
            self._sensor.set(occupancy=1 if occupied else 0)
        except OSError as exception:
            self._published = None
            error("occupancy", str(exception))
            return
        self._published = occupied


main()
