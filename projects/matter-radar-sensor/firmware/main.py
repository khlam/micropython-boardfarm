"""Publish radar occupancy and its configurable hold through Matter.

An HLK-LD2450 or HLK-LD2420 wired to the same UART is detected at startup, and
the product behaves identically either way. Each valid radar report updates a
read-only Occupancy Sensor endpoint. A virtual Dimmable Light controls how long
occupancy stays on after the first empty report, from zero to ten minutes. A
missing report or UART error forces occupancy on and restarts the radar
connection.

The board sends the same JSON reports over USB serial and its dashboard
WebSocket.
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
# Use every radar report for occupancy, but send at most two per second to the
# dashboard.
_DASHBOARD_REPORT_INTERVAL_MS = const(500)
# Ignore targets within this radius because ending tracks can move toward the
# sensor.
_DEAD_ZONE_RADIUS_MM = const(10)
# Matter uses light levels from 0 to 254. Map them to a zero-to-ten-minute hold.
_MATTER_LEVEL_MAXIMUM = const(254)
_MAXIMUM_HOLD_MS = const(600_000)

_OCCUPIED = const(0)
_EMPTY_HOLD = const(1)
_VACANT = const(2)

# Status colors keep commissioning failures distinct from normal commissioning.
# Amber means an uncommissioned node stopped advertising; yellow means a radar
# or Matter synchronization failure.
_BOOT_COLOR = (8, 8, 8)
_OCCUPIED_COLOR = (0, 8, 0)
_COMMISSIONING_WINDOW_COLOR = (8, 0, 8)
_COMMISSIONING_SESSION_COLOR = (0, 8, 8)
_COMMISSIONING_FAILED_COLOR = (8, 0, 0)
_COMMISSIONING_STOPPED_COLOR = (8, 4, 0)
_RADAR_FAILED_COLOR = (8, 8, 0)
_VACANT_COLOR = (0, 0, 8)


def main() -> None:
    """Initialize the product and run its tasks."""
    application = _Application()
    asyncio.run(application.run())


class _Application:
    """Own the Matter node, radar, dashboard, occupancy state, and status pixel."""

    def __init__(self) -> None:
        """Initialize hardware and start Matter before the async services."""
        self._commissioning_state = None
        self._commissioning_session_active = False
        self._matter_healthy = True
        self._radar_healthy = True
        self._occupancy_state = _OCCUPIED
        self._published_occupancy = None
        self._hold_started_ms = None
        self._dashboard_address = None
        self._dashboard_failed = False

        self._pixel = neopixel.NeoPixel(machine.Pin(BOARD.led_pin, machine.Pin.OUT), 1)
        self._set_pixel_color(_BOOT_COLOR)

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
        self._commissioned = bool(self._node.fabrics())
        self._update_status_pixel()

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
                    self._update_status_pixel()
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
        last_dashboard_report_ms = None

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

                self._set_occupied()
                self._set_radar_health(healthy=True)
                emit({"diag": "radar_ok", "model": model})

            try:
                targets = await radar.read_latest()
            except OSError as exception:
                self._handle_radar_failure(
                    radar,
                    {"diag": "read_err", "err": str(exception)},
                )
                radar = None
                await asyncio.sleep_ms(_RADAR_RETRY_MS)
                continue

            now_ms = time.ticks_ms()
            if targets is None:
                self._handle_radar_failure(
                    radar,
                    {"diag": "report_timeout", "t": now_ms},
                )
                radar = None
                await asyncio.sleep_ms(_RADAR_RETRY_MS)
                continue

            targets = tuple(target for target in targets if self._outside_dead_zone(target))
            self._apply_radar_report(occupied=bool(targets), now_ms=now_ms)
            if last_dashboard_report_ms is None or (
                time.ticks_diff(now_ms, last_dashboard_report_ms) >= _DASHBOARD_REPORT_INTERVAL_MS
            ):
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
                last_dashboard_report_ms = now_ms

    def _set_pixel_color(self, color: tuple) -> None:
        """Update the onboard status pixel when its color changes."""
        if self._pixel[0] == color:
            return
        self._pixel[0] = color
        self._pixel.write()

    def _update_status_pixel(self) -> None:
        """Show the highest-priority commissioning or product state.

        Commissioning outranks product state until the node is paired. A closed
        window can mean that commissioning started or that the window expired,
        so the active-session flag distinguishes those cases.
        """
        state = self._commissioning_state
        if state == matter.Commissioning.FAILED:
            color = _COMMISSIONING_FAILED_COLOR
        elif state == matter.Commissioning.OPENED:
            color = _COMMISSIONING_WINDOW_COLOR
        elif self._commissioning_session_active:
            color = _COMMISSIONING_SESSION_COLOR
        elif not self._commissioned:
            closed = state == matter.Commissioning.CLOSED
            color = _COMMISSIONING_STOPPED_COLOR if closed else _BOOT_COLOR
        elif not (self._matter_healthy and self._radar_healthy):
            color = _RADAR_FAILED_COLOR
        else:
            color = _VACANT_COLOR if self._occupancy_state == _VACANT else _OCCUPIED_COLOR
        self._set_pixel_color(color)

    def _on_commissioning(self, event: object) -> None:
        """Record one commissioning transition and update the pixel.

        A failure stays visible only until the next event. The Matter package
        opens another window if an uncommissioned node stops advertising, so a
        persistent red light means commissioning continues to fail.

        Args:
            event: Commissioning event delivered by the Matter node.
        """
        state = event.state
        if state == matter.Commissioning.STARTED:
            self._commissioning_session_active = True
        elif state in (matter.Commissioning.COMPLETE, matter.Commissioning.FAILED):
            self._commissioning_session_active = False
        if state == matter.Commissioning.COMPLETE:
            self._commissioned = True
        self._commissioning_state = state
        self._update_status_pixel()

    def _set_radar_health(self, *, healthy: bool) -> None:
        """Record radar health and update the status pixel."""
        self._radar_healthy = healthy
        self._update_status_pixel()

    def _handle_matter_events(self, events: tuple) -> None:
        """Apply the commissioning transitions returned by Matter."""
        for event in events:
            if isinstance(event, matter.CommissioningEvent):
                self._on_commissioning(event)

    def _publish_occupancy(self) -> None:
        """Publish the current occupancy state and retry failures later.

        A failed publish leaves the Python endpoint holding the requested value
        while ESP-Matter holds the previous one, so it clears the record of what
        was published and the next call republishes whatever the state is then.
        """
        occupied = self._occupancy_state != _VACANT
        if self._published_occupancy == occupied:
            return
        try:
            self._occupancy.set(occupancy=1 if occupied else 0)
        except OSError as exception:
            self._published_occupancy = None
            error("occupancy", str(exception))
            return
        self._published_occupancy = occupied

    def _occupancy_hold_ms(self) -> int:
        """Return the current controller-selected occupancy hold."""
        if not self._hold_control.on:
            return 0
        return self._hold_control.level * _MAXIMUM_HOLD_MS // _MATTER_LEVEL_MAXIMUM

    def _apply_radar_report(self, *, occupied: bool, now_ms: int) -> None:
        """Apply one valid radar report to the occupancy state.

        Args:
            occupied: Whether the report has a target outside the dead zone.
            now_ms: Monotonic time when the report was received.
        """
        if not self._matter_healthy or occupied:
            self._set_occupied()
        else:
            self._apply_empty_report(now_ms=now_ms)

    def _set_occupied(self) -> None:
        """Set occupied and cancel the current occupancy hold."""
        self._occupancy_state = _OCCUPIED
        self._hold_started_ms = None
        self._update_status_pixel()
        self._publish_occupancy()

    def _apply_empty_report(self, *, now_ms: int) -> None:
        """Start, continue, or finish the occupancy hold for an empty report.

        The pixel is only written when the rendered color can change, so
        starting a hold, which still reads as occupied, leaves it alone.

        Args:
            now_ms: Monotonic time when the report was received.
        """
        if self._occupancy_state == _OCCUPIED:
            self._occupancy_state = _EMPTY_HOLD
            self._hold_started_ms = now_ms

        if self._occupancy_state == _EMPTY_HOLD and (
            time.ticks_diff(now_ms, self._hold_started_ms) >= self._occupancy_hold_ms()
        ):
            self._occupancy_state = _VACANT
            self._hold_started_ms = None
            self._update_status_pixel()

        self._publish_occupancy()

    def _handle_radar_failure(self, radar: ReportStream | None, report: dict) -> None:
        """Force occupied, report the failure once, and close the radar.

        Args:
            radar: Current radar, if it was created.
            report: JSON diagnostic describing this failure.
        """
        first_failure = self._radar_healthy
        self._set_occupied()
        self._set_radar_health(healthy=False)
        if first_failure:
            emit(report)
        if radar is not None:
            try:  # noqa: SIM105 - contextlib is not available on MicroPython
                radar.close()
            except OSError:
                pass

    @staticmethod
    def _outside_dead_zone(target: object) -> bool:
        """Return whether a target is outside the ignored sensor radius."""
        distance_squared = target.x_mm * target.x_mm + target.y_mm * target.y_mm
        return distance_squared >= _DEAD_ZONE_RADIUS_MM * _DEAD_ZONE_RADIUS_MM

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


main()
