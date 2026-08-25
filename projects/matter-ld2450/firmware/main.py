"""Publish HLK-LD2450 occupancy and its configurable hold through Matter.

Each valid radar report updates a read-only Occupancy Sensor endpoint. A virtual
Dimmable Light controls how long occupancy stays on after the first empty
report, from zero to ten minutes. A missing report or UART error forces
occupancy on and restarts the radar connection.

The board sends the same JSON reports over USB serial and its dashboard
WebSocket. The dashboard is available at the network address assigned during
Matter commissioning, so it works with or without a USB host.
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
from ld2450 import LD2450, DeviceNotFoundError
from matter.emit import add_sink, emit, error

Board = namedtuple("Board", ("uart_id", "tx", "rx", "led_pin"))
_machine = os.uname().machine
if "ESP32S3" not in _machine:
    raise RuntimeError(f"unsupported board: {_machine}")
BOARD = Board(uart_id=1, tx=5, rx=6, led_pin=21)

_RADAR_RETRY_MS = const(1_000)
_MATTER_POLL_MS = const(50)
# Matter uses UDP ports 5540 and 5353, leaving the standard HTTP port available.
_DASHBOARD_PORT = const(80)
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

# CLOSED needs the tracked session state, so _commissioning_color handles it
# below.
_COMMISSIONING_COLORS = {
    matter.Commissioning.FAILED: _COMMISSIONING_FAILED_COLOR,
    matter.Commissioning.STARTED: _COMMISSIONING_SESSION_COLOR,
    matter.Commissioning.OPENED: _COMMISSIONING_WINDOW_COLOR,
}


def main() -> None:
    """Initialize the product and run its tasks."""
    application = _Application()
    asyncio.run(application.run())


class _Application:
    """Own the Matter node, radar, dashboard, occupancy state, and status pixel."""

    def __init__(self) -> None:
        """Initialize hardware and start Matter before the async services."""
        self._commissioned = False
        self._commissioning_state = None
        self._commissioning_session_active = False
        self._matter_healthy = True
        self._radar_healthy = None
        self._occupancy_state = _OCCUPIED
        self._published_occupancy = None
        self._hold_started_ms = None

        self._pixel = neopixel.NeoPixel(machine.Pin(BOARD.led_pin, machine.Pin.OUT), 1)
        self._set_pixel_color(_BOOT_COLOR)

        # Define routes now. Start the server after Matter has a network address.
        self._dashboard = httpd.Server(port=_DASHBOARD_PORT)
        self._dashboard.page(
            "/",
            dashboard_page.PAGE,
            content_type=dashboard_page.CONTENT_TYPE,
            encoding=dashboard_page.ENCODING,
        )
        dashboard_reports = self._dashboard.stream(
            "/ws",
            greeting=ujson.dumps({"event": "connected", "port": f"ld2450 uart{BOARD.uart_id}"}),
        )
        add_sink(dashboard_reports.send)

        self._node = matter.Node()
        # Endpoint IDs persist, so always create the occupancy endpoint first.
        self._occupancy = self._node.create_endpoint(matter.EndpointType.OCCUPANCY_SENSOR)
        self._hold_control = self._node.create_endpoint(matter.EndpointType.DIMMABLE_LIGHT)
        self._node.start()

        # The product contract requires occupied during startup and radar recovery.
        self._publish_occupancy()
        self._commissioned = bool(self._node.fabrics()) or self._commissioned
        self._update_status_pixel()

    async def run(self) -> None:
        """Run Matter polling, dashboard, and radar tasks."""
        await asyncio.gather(self._run_matter(), self._run_dashboard(), self._run_radar())

    async def _run_matter(self) -> None:
        """Poll Matter and hold fail-safe occupied through failure periods."""
        failure_reported = False
        while True:
            try:
                events = self._node.poll()
            except OSError as exception:
                self._set_matter_health(healthy=False)
                self._set_occupied()
                if not failure_reported:
                    emit({"diag": "matter_poll_err", "err": str(exception)})
                failure_reported = True
            else:
                if failure_reported:
                    emit({"diag": "matter_ok"})
                failure_reported = False
                self._set_matter_health(healthy=True)
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
        address = None
        failure_reported = False
        await asyncio.sleep_ms(_DASHBOARD_BOOT_DELAY_MS)

        while True:
            address, failure_reported, delay_ms = await self._update_dashboard(
                address, failure_reported=failure_reported
            )
            await asyncio.sleep_ms(delay_ms)

    async def _run_radar(self) -> None:
        """Read radar reports and recreate the radar after a failure."""
        radar = None
        failure_reported = False
        last_dashboard_report_ms = None

        while True:
            if radar is None:
                new_radar = None
                try:
                    new_radar = LD2450(bus_id=BOARD.uart_id, tx=BOARD.tx, rx=BOARD.rx)
                    await new_radar.wait_ready()
                except (DeviceNotFoundError, OSError) as exception:
                    diagnostic = (
                        "no_device" if isinstance(exception, DeviceNotFoundError) else "init_err"
                    )
                    failure_reported = self._handle_radar_failure(
                        new_radar,
                        diagnostic=diagnostic,
                        exception=exception,
                        already_reported=failure_reported,
                    )
                    await asyncio.sleep_ms(_RADAR_RETRY_MS)
                    continue

                radar = new_radar
                self._set_occupied()
                self._set_radar_health(healthy=True)
                emit({"diag": "radar_ok"})
                failure_reported = False

            try:
                targets = await radar.read_latest()
            except OSError as exception:
                failure_reported = self._handle_radar_failure(
                    radar,
                    diagnostic="read_err",
                    exception=exception,
                    already_reported=failure_reported,
                )
                radar = None
                await asyncio.sleep_ms(_RADAR_RETRY_MS)
                continue

            now_ms = time.ticks_ms()
            if targets is None:
                failure_reported = self._handle_radar_failure(
                    radar,
                    diagnostic="report_timeout",
                    now_ms=now_ms,
                    already_reported=failure_reported,
                )
                radar = None
                await asyncio.sleep_ms(_RADAR_RETRY_MS)
                continue

            targets = tuple(target for target in targets if self._outside_dead_zone(target))
            self._set_radar_health(healthy=True)
            self._apply_radar_report(occupied=bool(targets), now_ms=now_ms)
            dashboard_report_due = last_dashboard_report_ms is None or (
                time.ticks_diff(now_ms, last_dashboard_report_ms) >= _DASHBOARD_REPORT_INTERVAL_MS
            )
            if dashboard_report_due:
                emit({"t": now_ms, "targets": [self._target_fields(target) for target in targets]})
                last_dashboard_report_ms = now_ms

    def _set_pixel_color(self, color: tuple) -> None:
        """Set the onboard status pixel color."""
        self._pixel[0] = color
        self._pixel.write()

    def _commissioning_color(self) -> tuple | None:
        """Return the commissioning color, or None after commissioning.

        A closed window can mean that commissioning started or that the window
        expired. The active-session flag distinguishes those cases.
        """
        color = _COMMISSIONING_COLORS.get(self._commissioning_state)
        if color is not None:
            return color
        if self._commissioning_session_active:
            return _COMMISSIONING_SESSION_COLOR
        if self._commissioned:
            return None
        if self._commissioning_state == matter.Commissioning.CLOSED:
            return _COMMISSIONING_STOPPED_COLOR
        return _BOOT_COLOR

    def _update_status_pixel(self) -> None:
        """Show the highest-priority commissioning or product state."""
        color = self._commissioning_color()
        if color is None:
            if not self._matter_healthy or self._radar_healthy is False:
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
        """Record radar health and update the status pixel when it changes."""
        if self._radar_healthy == healthy:
            return
        self._radar_healthy = healthy
        self._update_status_pixel()

    def _set_matter_health(self, *, healthy: bool) -> None:
        """Record Matter synchronization health and update the status pixel."""
        if self._matter_healthy == healthy:
            return
        self._matter_healthy = healthy
        self._update_status_pixel()

    def _handle_matter_events(self, events: tuple) -> None:
        """Apply explicit commissioning events returned by Matter.

        Args:
            events: Revision-ordered events returned by ``Node.poll()``.
        """
        for event in events:
            if isinstance(event, matter.CommissioningEvent):
                self._on_commissioning(event)

    def _publish_occupancy(self, *, force: bool = False) -> None:
        """Publish the current occupancy state and retry failures later.

        Args:
            force: Publish even if this value was published successfully before.
                A failed publish changes the Python endpoint value, so a later
                state change must restore that value.
        """
        occupied = self._occupancy_state != _VACANT
        if not force and self._published_occupancy == occupied:
            return
        try:
            self._occupancy.set(occupancy=1 if occupied else 0)
        except OSError as exception:
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
        force = self._occupancy_state == _VACANT
        self._occupancy_state = _OCCUPIED
        self._hold_started_ms = None
        self._update_status_pixel()
        self._publish_occupancy(force=force)

    def _apply_empty_report(self, *, now_ms: int) -> None:
        """Start, continue, or finish the occupancy hold for an empty report.

        Args:
            now_ms: Monotonic time when the report was received.
        """
        if self._occupancy_state == _VACANT:
            self._publish_occupancy()
            return

        if self._occupancy_state == _OCCUPIED:
            self._occupancy_state = _EMPTY_HOLD
            self._hold_started_ms = now_ms
            self._update_status_pixel()

        try:
            hold_ms = self._occupancy_hold_ms()
        except (OSError, ValueError) as exception:
            error("hold_control", str(exception))
            self._set_occupied()
            return

        hold_started_ms = self._hold_started_ms
        if hold_started_ms is None:
            self._set_occupied()
            return
        if time.ticks_diff(now_ms, hold_started_ms) < hold_ms:
            self._publish_occupancy()
            return

        self._occupancy_state = _VACANT
        self._hold_started_ms = None
        self._update_status_pixel()
        self._publish_occupancy(force=True)

    def _handle_radar_failure(
        self,
        radar: LD2450 | None,
        *,
        diagnostic: str,
        already_reported: bool,
        exception: Exception | None = None,
        now_ms: int | None = None,
    ) -> bool:
        """Force occupied, report the failure once, and close the radar.

        Args:
            radar: Current radar, if it was created.
            diagnostic: JSON diagnostic value for the failure.
            already_reported: Whether this failure period has been reported.
            exception: Error that caused the failure, if available.
            now_ms: Time of a missing report, if available.

        Returns:
            True because this failure period has now been reported.
        """
        self._set_occupied()
        self._set_radar_health(healthy=False)
        if not already_reported:
            report = {"diag": diagnostic}
            if exception is not None:
                report["err"] = str(exception)
            if now_ms is not None:
                report["t"] = now_ms
            emit(report)
        self._close_radar(radar)
        return True

    @staticmethod
    def _close_radar(radar: LD2450 | None) -> None:
        """Close the radar without letting a close error stop recovery."""
        if radar is None:
            return
        try:
            radar.close()
        except Exception:  # noqa: BLE001 - a UART close error must not stop recovery.
            return

    @staticmethod
    def _target_fields(target: object) -> dict:
        """Return one radar target in the dashboard JSON format."""
        return {
            "slot": target.slot,
            "x_mm": target.x_mm,
            "y_mm": target.y_mm,
            "speed_cm_s": target.speed_cm_s,
            "resolution_mm": target.resolution_mm,
        }

    @staticmethod
    def _outside_dead_zone(target: object) -> bool:
        """Return whether a target is outside the ignored sensor radius."""
        distance_squared = target.x_mm * target.x_mm + target.y_mm * target.y_mm
        return distance_squared >= _DEAD_ZONE_RADIUS_MM * _DEAD_ZONE_RADIUS_MM

    def _dashboard_address(self) -> tuple[str | None, OSError | None]:
        """Return the current network address and any lookup error."""
        try:
            return self._node.network_address(), None
        except OSError as exception:
            return None, exception

    @staticmethod
    def _report_dashboard_failure(exception: OSError, *, already_reported: bool) -> bool:
        """Report a dashboard failure once during each failure period.

        Args:
            exception: Dashboard error to report.
            already_reported: Whether this failure period has been reported.

        Returns:
            True because this failure period has now been reported.
        """
        if not already_reported:
            error("dashboard", str(exception))
        return True

    @staticmethod
    def _report_dashboard_ready(address: str) -> None:
        """Report the address of the running dashboard."""
        emit({"event": "dashboard", "state": "ready", "url": "http://" + address + "/"})

    async def _start_dashboard(self, address: str) -> OSError | None:
        """Start the dashboard and report its address or return an error."""
        try:
            await self._dashboard.start()
        except OSError as exception:
            return exception
        self._report_dashboard_ready(address)
        return None

    async def _update_dashboard(
        self, address: str | None, *, failure_reported: bool
    ) -> tuple[str | None, bool, int]:
        """Check the dashboard and return the state for the next check.

        Args:
            address: Last reported address for the dashboard server.
            failure_reported: Whether this failure period has been reported.

        Returns:
            Address, error-report flag, and delay before the next check.
        """
        current_address, address_error = self._dashboard_address()
        if address_error is not None:
            failure_reported = self._report_dashboard_failure(
                address_error, already_reported=failure_reported
            )
            return address, failure_reported, _ADDRESS_POLL_MS
        if current_address is None:
            return None, False, _ADDRESS_POLL_MS
        if not self._dashboard.running:
            start_error = await self._start_dashboard(current_address)
            if start_error is not None:
                failure_reported = self._report_dashboard_failure(
                    start_error, already_reported=failure_reported
                )
                return address, failure_reported, _DASHBOARD_RETRY_MS
            return current_address, False, _ADDRESS_POLL_MS
        if current_address != address:
            self._report_dashboard_ready(current_address)
        return current_address, False, _ADDRESS_POLL_MS


main()
