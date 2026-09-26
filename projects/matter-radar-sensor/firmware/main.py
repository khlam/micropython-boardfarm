"""Publish radar occupancy and its configurable hold through Matter.

An HLK-LD2450 or HLK-LD2420 wired to the same UART is detected at startup, and
the product behaves identically either way. Each valid radar report updates a
read-only Occupancy Sensor endpoint. A virtual Dimmable Light controls how long
occupancy stays on after the first empty report, from zero to ten minutes. A
missing report or UART error forces occupancy on and restarts the radar
connection.

This module wires the hardware and runs Matter polling, the dashboard, and radar
reading, applying each report to occupancy before its telemetry. The reports
module decides occupancy and telemetry pacing; StatusPixel owns commissioning
state and LED priority.

The board sends the same JSON lines over USB serial and its dashboard WebSocket.
"""

import asyncio
import os
import time
from collections import namedtuple

import dashboard_page
import machine
import neopixel
import ujson
from micropython import const
from reports import Occupancy, ReportThrottle, hold_ms, outside_dead_zone
from status import StatusPixel

import httpd
import matter
from matter.emit import add_sink, emit, error
from radar import NoRadarError, ReportStream, detect

# Pin map for this board, shared by every supported radar. ``tx`` connects to
# radar RX, ``rx`` to radar TX, and ``led_pin`` drives the onboard WS2812. Only
# ESP32-S3 is supported.
Board = namedtuple("Board", ("name", "uart_id", "tx", "rx", "led_pin"))
_machine = os.uname().machine
if "ESP32S3" not in _machine:
    raise RuntimeError(f"unsupported board: {_machine}")
BOARD = Board(name="ESP32-S3-Zero", uart_id=1, tx=5, rx=6, led_pin=21)

_RADAR_RETRY_MS = const(1_000)
_MATTER_POLL_MS = const(50)
# Poll because Matter does not report address changes to this application.
_ADDRESS_POLL_MS = const(1_000)
# Let Matter finish its high-current startup before starting more network work.
_DASHBOARD_BOOT_DELAY_MS = const(15_000)
_DASHBOARD_RETRY_MS = const(5_000)


def main() -> None:
    """Initialize the product and run its tasks."""
    application = _Application()
    asyncio.run(application.run())


class _Application:
    """Wire services and own the radar-to-Matter occupancy policy."""

    def __init__(self) -> None:
        """Initialize hardware and start Matter before the async services."""
        self._matter_healthy = True
        self._radar_healthy = True
        self._occupancy_policy = Occupancy()
        self._throttle = ReportThrottle()
        self._published_occupancy = None
        self._dashboard_address = None
        self._dashboard_failed = False

        pixel = neopixel.NeoPixel(machine.Pin(BOARD.led_pin, machine.Pin.OUT), 1)
        self._status = StatusPixel(pixel)

        # Define routes now. Start the server after Matter has a network address.
        self._dashboard = httpd.Server()
        self._dashboard.page(
            "/",
            dashboard_page.PAGE,
            encoding=dashboard_page.ENCODING,
        )
        dashboard_reports = self._dashboard.stream(
            "/ws",
            # The radar model is only known after detection, so it arrives later
            # with the radar_ok diagnostic instead.
            greeting=ujson.dumps({"event": "connected", "port": f"radar uart{BOARD.uart_id}"}),
        )
        add_sink(dashboard_reports.send)

        self._node = matter.Node()
        # Endpoint IDs persist, so always create the occupancy endpoint first.
        self._occupancy = self._node.create_endpoint(matter.EndpointType.OCCUPANCY_SENSOR)
        self._hold_control = self._node.create_endpoint(matter.EndpointType.DIMMABLE_LIGHT)
        self._node.start()

        # The product contract requires occupied during startup and radar recovery.
        self._publish_occupancy()
        self._status.set_commissioned(value=bool(self._node.fabrics()))

    async def run(self) -> None:
        """Run Matter polling, dashboard, and radar tasks."""
        await asyncio.gather(self._run_matter(), self._run_dashboard(), self._run_radar())

    async def _run_matter(self) -> None:
        """Poll Matter and hold fail-safe occupied through failure periods."""
        while True:
            try:
                events = self._node.poll()
            except OSError as exception:
                first_failure = self._matter_healthy
                self._matter_healthy = False
                self._set_occupied()
                if first_failure:
                    emit({"diag": "matter_poll_err", "err": str(exception)})
            else:
                if not self._matter_healthy:
                    emit({"diag": "matter_ok"})
                    self._matter_healthy = True
                    self._update_status()
                self._handle_matter_events(events)
            await asyncio.sleep_ms(_MATTER_POLL_MS)

    async def _run_dashboard(self) -> None:
        """Keep the dashboard available after Matter has a network address.

        Wait for Matter startup before adding a server and more network traffic.
        The server listens on every interface, so an address change only needs
        a new dashboard address report.

        Report each dashboard failure period once and keep retrying. Dashboard
        failures do not change occupancy.
        """
        await asyncio.sleep_ms(_DASHBOARD_BOOT_DELAY_MS)
        while True:
            await asyncio.sleep_ms(await self._update_dashboard())

    async def _run_radar(self) -> None:
        """Read radar reports and re-detect the radar after a failure."""
        radar = None

        while True:
            if radar is None:
                try:
                    model, radar = await detect(bus_id=BOARD.uart_id, tx=BOARD.tx, rx=BOARD.rx)
                except (NoRadarError, OSError) as exception:
                    diagnostic = "no_device" if isinstance(exception, NoRadarError) else "init_err"
                    # detect() released every probe it opened, so there is
                    # nothing left here to close.
                    self._handle_radar_failure(
                        None,
                        {"diag": diagnostic, "err": str(exception)},
                    )
                    await asyncio.sleep_ms(_RADAR_RETRY_MS)
                    continue

                self._radar_healthy = True
                self._set_occupied()
                emit({"diag": "radar_ok", "model": model})

            try:
                targets = await radar.read_latest()
            except OSError as exception:
                report = {"diag": "read_err", "err": str(exception)}
            else:
                now_ms = time.ticks_ms()
                if targets is not None:
                    self._handle_targets(targets, now_ms)
                    continue
                report = {"diag": "report_timeout", "t": now_ms}

            self._handle_radar_failure(radar, report)
            radar = None
            await asyncio.sleep_ms(_RADAR_RETRY_MS)

    def _handle_matter_events(self, events: tuple) -> None:
        """Send commissioning transitions to the status pixel."""
        for event in events:
            if isinstance(event, matter.CommissioningEvent):
                self._status.on_commissioning(event)

    def _handle_radar_failure(self, radar: ReportStream | None, report: dict) -> None:
        """Force occupied, report the failure once, and close the radar.

        Args:
            radar: Current radar, if it was created.
            report: JSON diagnostic describing this failure.
        """
        first_failure = self._radar_healthy
        self._radar_healthy = False
        self._set_occupied()
        if first_failure:
            emit(report)
        if radar is not None:
            try:  # noqa: SIM105 - contextlib is not available on MicroPython
                radar.close()
            except OSError:
                pass

    def _handle_targets(self, targets: tuple, now_ms: int) -> None:
        """Apply one valid report to occupancy, then send its telemetry when due.

        Args:
            targets: Targets from the report, including any in the dead zone.
            now_ms: Monotonic time when the report was received.
        """
        targets = tuple(target for target in targets if outside_dead_zone(target))
        self._apply_radar_report(occupied=bool(targets), now_ms=now_ms)
        if self._throttle.due(now_ms):
            _emit_targets(targets, now_ms)

    def _apply_radar_report(self, *, occupied: bool, now_ms: int) -> None:
        """Apply one valid radar report, holding occupied while Matter is failing.

        Args:
            occupied: Whether the report has a target outside the dead zone.
            now_ms: Monotonic time when the report was received.
        """
        self._occupancy_policy.report(
            occupied=occupied or not self._matter_healthy,
            now_ms=now_ms,
            hold_ms=hold_ms(on=self._hold_control.on, level=self._hold_control.level),
        )
        self._update_status()
        self._publish_occupancy()

    def _set_occupied(self) -> None:
        """Set occupied and cancel the current occupancy hold."""
        self._occupancy_policy.force_occupied()
        self._update_status()
        self._publish_occupancy()

    def _update_status(self) -> None:
        """Send the current occupancy and combined health to the status pixel."""
        self._status.update_product(
            occupied=self._occupancy_policy.occupied,
            healthy=self._matter_healthy and self._radar_healthy,
        )

    def _publish_occupancy(self) -> None:
        """Publish the current occupancy state and retry failures later.

        A failed publish leaves the Python endpoint holding the requested value
        while ESP-Matter holds the previous one, so it clears the record of what
        was published and the next call republishes whatever the state is then.
        """
        occupied = self._occupancy_policy.occupied
        if self._published_occupancy == occupied:
            return
        try:
            self._occupancy.set(occupancy=1 if occupied else 0)
        except OSError as exception:
            self._published_occupancy = None
            error("occupancy", str(exception))
            return
        self._published_occupancy = occupied

    async def _update_dashboard(self) -> int:
        """Check the dashboard once and return the delay before the next check.

        A failure keeps the last reported address and is written out only once
        per failure period.

        Returns:
            Milliseconds to wait before checking again.
        """
        retry_ms = _ADDRESS_POLL_MS
        try:
            address = self._node.network_address()
            if address is not None:
                retry_ms = _DASHBOARD_RETRY_MS
                await self._dashboard.start()
        except OSError as exception:
            if not self._dashboard_failed:
                error("dashboard", str(exception))
            self._dashboard_failed = True
            return retry_ms
        if address is not None and address != self._dashboard_address:
            emit({"event": "dashboard", "state": "ready", "url": "http://" + address + "/"})
        self._dashboard_address = address
        self._dashboard_failed = False
        return _ADDRESS_POLL_MS


def _emit_targets(targets: tuple, now_ms: int) -> None:
    """Emit one telemetry line for the filtered targets of a radar report."""
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


main()
