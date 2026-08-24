"""Publish HLK-LD2450 occupancy and its configurable hold through Matter.

The newest complete radar report controls one read-only Occupancy Sensor
endpoint. A virtual Dimmable Light configures how long a falling occupancy
transition is held, from zero to ten minutes. Missing reports mark the radar
unhealthy, force occupancy on, and recreate the radar connection.

The same diagnostic stream leaves the board twice: over USB serial, and over a
WebSocket on the address Matter commissioning put the board on. Both carry the
identical JSON lines to the identical dashboard, so the board can be watched
with or without a host attached to its serial port.
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

_RETRY_PAUSE_MS = const(1_000)
# CHIP holds UDP 5540 and mDNS holds 5353, so the ordinary web port is free.
_DASHBOARD_PORT = const(80)
# There is no event for the address arriving, and it can change with the DHCP
# lease, so the address is polled for as long as the firmware runs.
_ADDRESS_POLL_MS = const(1_000)
# Leave Matter alone during the startup current peak before diagnostics may add
# another listener and network traffic.
_DASHBOARD_BOOT_DELAY_MS = const(15_000)
_DASHBOARD_RETRY_MS = const(5_000)
# Occupancy still consumes every report; only the diagnostic copy is decimated.
_REPORT_STREAM_INTERVAL_MS = const(500)
# Near-field reports can collapse toward the origin as tracking ends. Ignore
# radius around the sensor so those artifacts cannot hold occupancy on.
_DEAD_ZONE_RADIUS_MM = const(10)
# Matter renders CurrentLevel 0-254 as brightness 0-100 percent. This virtual
# light uses that range as a continuous zero-to-ten-minute occupancy hold.
_MATTER_LEVEL_MAXIMUM = const(254)
_MAXIMUM_HOLD_MS = const(600_000)

_OCCUPIED = const(0)
_EMPTY_HOLD = const(1)
_VACANT = const(2)

# One colour per state a node can be in before it is paired, because the
# failures worth catching are the ones where it stops advertising: a node nobody
# can reach has to look different from one waiting to be scanned. Amber is that
# state, so radar trouble takes yellow rather than sharing it.
BOOT_COLOR = (8, 8, 8)
GREEN_COLOR = (0, 8, 0)
WINDOW_COLOR = (8, 0, 8)
SESSION_COLOR = (0, 8, 8)
FAILED_COLOR = (8, 0, 0)
STALLED_COLOR = (8, 4, 0)
RADAR_FAULT_COLOR = (8, 8, 0)
CLEAR_COLOR = (0, 0, 8)

# States that name their own colour outright. CLOSED is deliberately absent: it
# is the ambiguous one, resolved against the tracked session in _pairing_color.
_COMMISSIONING_COLORS = {
    matter.Commissioning.FAILED: FAILED_COLOR,
    matter.Commissioning.STARTED: SESSION_COLOR,
    matter.Commissioning.OPENED: WINDOW_COLOR,
}


def main() -> None:
    """Initialize the product and run its concurrent services."""
    application = _Application()
    asyncio.run(application.run())


class _Application:
    """Own the Matter node, dashboard, radar policy, and visible product state."""

    def __init__(self) -> None:
        """Initialize hardware and start Matter before the async services."""
        self._commissioned = False
        self._commissioning = None
        self._session_active = False
        self._radar_ok = None
        self._occupancy_state = _OCCUPIED
        self._published_occupancy = None
        self._empty_started_ms = None

        self._pixel = neopixel.NeoPixel(machine.Pin(BOARD.led_pin, machine.Pin.OUT), 1)
        self._render_pixel(BOOT_COLOR)

        # Configure routes now; the listener starts after Matter obtains an address.
        self._dashboard = httpd.Server(port=_DASHBOARD_PORT)
        self._dashboard.page(
            "/",
            dashboard_page.PAGE,
            content_type=dashboard_page.CONTENT_TYPE,
            encoding=dashboard_page.ENCODING,
        )
        reports = self._dashboard.stream(
            "/ws",
            greeting=ujson.dumps({"event": "connected", "port": f"ld2450 uart{BOARD.uart_id}"}),
        )
        add_sink(reports.send)

        self._node = matter.Node()
        # Endpoint order is persistent, so occupancy must retain the first ID.
        self._occupancy = self._node.create_endpoint(matter.EndpointType.OCCUPANCY_SENSOR)
        self._hold_control = self._node.create_endpoint(matter.EndpointType.DIMMABLE_LIGHT)
        self._node.on_commissioning(self._on_commissioning)
        self._node.start()

        # Occupied is the fail-safe value while radar initialization proceeds.
        self._publish_desired_occupancy()
        self._commissioned = bool(self._node.fabrics()) or self._commissioned
        self._refresh_pixel()

    async def run(self) -> None:
        """Serve diagnostics while supervising radar occupancy indefinitely."""
        await asyncio.gather(self._serve_dashboard(), self._supervise_radar())

    def _render_pixel(self, color: tuple) -> None:
        """Drive the onboard pixel."""
        self._pixel[0] = color
        self._pixel.write()

    def _pairing_color(self) -> tuple | None:
        """Return the current pairing color, or None when product state owns the pixel.

        A closed window can mean either that a commissioner took it or that it
        expired. The tracked session distinguishes healthy pairing from a node
        that is no longer advertising.
        """
        color = _COMMISSIONING_COLORS.get(self._commissioning)
        if color is not None:
            return color
        if self._session_active:
            return SESSION_COLOR
        if self._commissioned:
            return None
        if self._commissioning == matter.Commissioning.CLOSED:
            return STALLED_COLOR
        return BOOT_COLOR

    def _refresh_pixel(self) -> None:
        """Render the highest-priority commissioning or product state."""
        color = self._pairing_color()
        if color is None:
            if self._radar_ok is False:
                color = RADAR_FAULT_COLOR
            else:
                color = CLEAR_COLOR if self._occupancy_state == _VACANT else GREEN_COLOR
        self._render_pixel(color)

    def _on_commissioning(self, event: object) -> None:
        """Record one commissioning transition and update the pixel.

        A failure is rendered but not latched. The Matter package reopens a
        window whenever an unpaired node would otherwise stop advertising, so a
        persistent red state signals a genuine failure.

        Args:
            event: Commissioning event delivered by the Matter node.
        """
        state = event.state
        if state == matter.Commissioning.STARTED:
            self._session_active = True
        elif state in (matter.Commissioning.COMPLETE, matter.Commissioning.FAILED):
            self._session_active = False
        if state == matter.Commissioning.COMPLETE:
            self._commissioned = True
        self._commissioning = state
        self._refresh_pixel()

    def _set_radar_ok(self, *, ok: bool) -> None:
        """Record a radar health transition and update the pixel."""
        if self._radar_ok == ok:
            return
        self._radar_ok = ok
        self._refresh_pixel()

    def _publish_desired_occupancy(self, *, force: bool = False) -> None:
        """Publish desired occupancy, leaving failures pending for retry.

        Args:
            force: Publish even when the desired value was last published
                successfully. A failed publish changes the endpoint's Python
                copy, so a later policy reversal must restore that copy too.
        """
        occupied = self._occupancy_state != _VACANT
        if not force and self._published_occupancy == occupied:
            return
        try:
            self._occupancy.occupancy = 1 if occupied else 0
        except OSError as err:
            error("occupancy", str(err))
            return
        self._published_occupancy = occupied

    def _configured_hold_ms(self) -> int:
        """Return the live controller-selected occupancy hold in milliseconds."""
        if not self._hold_control.on:
            return 0
        return self._hold_control.level * _MAXIMUM_HOLD_MS // _MATTER_LEVEL_MAXIMUM

    def _reconcile_occupancy(self, *, occupied: bool, now_ms: int) -> None:
        """Apply one valid radar observation to the held occupancy state.

        Args:
            occupied: Whether the report contains a target outside the dead zone.
            now_ms: Monotonic tick captured for this report.
        """
        if occupied:
            self._observe_occupied()
        else:
            self._observe_empty(now_ms=now_ms)

    def _observe_occupied(self) -> None:
        """Publish an occupied observation and cancel any pending clear."""
        force = self._occupancy_state == _VACANT
        self._occupancy_state = _OCCUPIED
        self._empty_started_ms = None
        self._refresh_pixel()
        self._publish_desired_occupancy(force=force)

    def _observe_empty(self, *, now_ms: int) -> None:
        """Publish or defer one valid empty observation.

        Args:
            now_ms: Monotonic tick captured for this report.
        """
        if self._occupancy_state == _VACANT:
            self._publish_desired_occupancy()
            return

        if self._occupancy_state == _OCCUPIED:
            self._occupancy_state = _EMPTY_HOLD
            self._empty_started_ms = now_ms
            self._refresh_pixel()

        try:
            hold_ms = self._configured_hold_ms()
        except (OSError, ValueError) as err:
            error("hold_control", str(err))
            self._observe_occupied()
            return

        empty_started_ms = self._empty_started_ms
        if empty_started_ms is None:
            self._observe_occupied()
            return
        if time.ticks_diff(now_ms, empty_started_ms) < hold_ms:
            self._publish_desired_occupancy()
            return

        self._occupancy_state = _VACANT
        self._empty_started_ms = None
        self._refresh_pixel()
        self._publish_desired_occupancy(force=True)

    async def _supervise_radar(self) -> None:
        """Recreate a failed radar while keeping Matter and diagnostics running."""
        radar = None
        failure_reported = False
        last_stream_ms = None

        while True:
            if radar is None:
                candidate = None
                try:
                    candidate = LD2450(bus_id=BOARD.uart_id, tx=BOARD.tx, rx=BOARD.rx)
                    await candidate.wait_ready()
                except (DeviceNotFoundError, OSError) as err:
                    diag = "no_device" if isinstance(err, DeviceNotFoundError) else "init_err"
                    failure_reported = self._enter_radar_fault(
                        candidate,
                        diag=diag,
                        err=err,
                        already_reported=failure_reported,
                    )
                    await asyncio.sleep_ms(_RETRY_PAUSE_MS)
                    continue

                radar = candidate
                self._observe_occupied()
                self._set_radar_ok(ok=True)
                emit({"diag": "radar_ok"})
                failure_reported = False

            try:
                targets = await radar.read_latest()
            except OSError as err:
                failure_reported = self._enter_radar_fault(
                    radar,
                    diag="read_err",
                    err=err,
                    already_reported=failure_reported,
                )
                radar = None
                await asyncio.sleep_ms(_RETRY_PAUSE_MS)
                continue

            now_ms = time.ticks_ms()
            if targets is None:
                failure_reported = self._enter_radar_fault(
                    radar,
                    diag="report_timeout",
                    now_ms=now_ms,
                    already_reported=failure_reported,
                )
                radar = None
                await asyncio.sleep_ms(_RETRY_PAUSE_MS)
                continue

            targets = tuple(target for target in targets if self._outside_dead_zone(target))
            self._set_radar_ok(ok=True)
            self._reconcile_occupancy(occupied=bool(targets), now_ms=now_ms)
            stream_due = last_stream_ms is None or (
                time.ticks_diff(now_ms, last_stream_ms) >= _REPORT_STREAM_INTERVAL_MS
            )
            if stream_due:
                emit({"t": now_ms, "targets": [self._target_dict(target) for target in targets]})
                last_stream_ms = now_ms

    def _enter_radar_fault(
        self,
        radar: LD2450 | None,
        *,
        diag: str,
        already_reported: bool,
        err: Exception | None = None,
        now_ms: int | None = None,
    ) -> bool:
        """Apply the fail-safe state and tear down one failed radar.

        Args:
            radar: Current driver, if construction completed.
            diag: Diagnostic category for the initiating fault.
            already_reported: Whether this failure period was already reported.
            err: Optional exception that caused the failure.
            now_ms: Optional report-timeout timestamp.

        Returns:
            True, recording that this failure period emitted its diagnostic.
        """
        self._observe_occupied()
        self._set_radar_ok(ok=False)
        if not already_reported:
            report = {"diag": diag}
            if err is not None:
                report["err"] = str(err)
            if now_ms is not None:
                report["t"] = now_ms
            emit(report)
        self._close_radar(radar)
        return True

    @staticmethod
    def _close_radar(radar: LD2450 | None) -> None:
        """Close a radar without allowing teardown failure to stop recovery."""
        if radar is None:
            return
        try:
            radar.close()
        except Exception:  # noqa: BLE001 - recovery must survive UART teardown failure.
            return

    @staticmethod
    def _target_dict(target: object) -> dict:
        """Convert one radar target to its raw dashboard fields."""
        return {
            "slot": target.slot,
            "x_mm": target.x_mm,
            "y_mm": target.y_mm,
            "speed_cm_s": target.speed_cm_s,
            "resolution_mm": target.resolution_mm,
        }

    @staticmethod
    def _outside_dead_zone(target: object) -> bool:
        """Return whether a target lies beyond the sensor's near-field radius."""
        distance_squared = target.x_mm * target.x_mm + target.y_mm * target.y_mm
        return distance_squared >= _DEAD_ZONE_RADIUS_MM * _DEAD_ZONE_RADIUS_MM

    def _dashboard_address(self) -> tuple[str | None, OSError | None]:
        """Return the current address and any recoverable lookup error."""
        try:
            return self._node.network_address(), None
        except OSError as err:
            return None, err

    @staticmethod
    def _report_dashboard_error(err: OSError, *, already_reported: bool) -> bool:
        """Emit one dashboard error per failure period and mark it reported.

        Args:
            err: The recoverable dashboard failure.
            already_reported: Whether this failure period already emitted an error.

        Returns:
            True, marking this failure period as reported.
        """
        if not already_reported:
            error("dashboard", str(err))
        return True

    @staticmethod
    def _report_dashboard_ready(address: str) -> None:
        """Emit the address of a running dashboard."""
        emit({"event": "dashboard", "state": "ready", "url": "http://" + address + "/"})

    async def _start_dashboard(self, address: str) -> OSError | None:
        """Start and announce the dashboard, returning a recoverable failure."""
        try:
            await self._dashboard.start()
        except OSError as err:
            return err
        self._report_dashboard_ready(address)
        return None

    async def _reconcile_dashboard(
        self, address: str | None, *, reported_error: bool
    ) -> tuple[str | None, bool, int]:
        """Reconcile one dashboard poll and return its next state.

        Args:
            address: Last address announced for the running listener.
            reported_error: Whether this failure period already emitted an error.

        Returns:
            Address, error-report flag, and delay before the next poll.
        """
        current, address_error = self._dashboard_address()
        if address_error is not None:
            reported_error = self._report_dashboard_error(
                address_error, already_reported=reported_error
            )
            return address, reported_error, _ADDRESS_POLL_MS
        if current is None:
            return None, False, _ADDRESS_POLL_MS
        if not self._dashboard.running:
            start_error = await self._start_dashboard(current)
            if start_error is not None:
                reported_error = self._report_dashboard_error(
                    start_error, already_reported=reported_error
                )
                return address, reported_error, _DASHBOARD_RETRY_MS
            return current, False, _ADDRESS_POLL_MS
        if current != address:
            self._report_dashboard_ready(current)
        return current, False, _ADDRESS_POLL_MS

    async def _serve_dashboard(self) -> None:
        """Keep the dashboard available once Matter networking has an address.

        Matter gets an undisturbed startup interval before diagnostics add
        another listener and network traffic. The listener binds every
        interface, so a later lease change only needs a fresh address report.

        Dashboard failures are reported once per failure period and retried;
        diagnostics must never take occupancy down.
        """
        address = None
        reported_error = False
        await asyncio.sleep_ms(_DASHBOARD_BOOT_DELAY_MS)

        while True:
            address, reported_error, delay_ms = await self._reconcile_dashboard(
                address, reported_error=reported_error
            )
            await asyncio.sleep_ms(delay_ms)


main()
