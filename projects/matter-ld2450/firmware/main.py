"""Publish HLK-LD2450 occupancy through Matter and stream radar diagnostics.

The newest complete radar report controls one read-only Occupancy Sensor
endpoint. Missing reports mark the radar unhealthy without clearing the last
published occupancy value.

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
_READ_ERR_PAUSE_MS = const(200)
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


class _ProductState:
    """Mutable state shared by radar and commissioning callbacks."""

    def __init__(self) -> None:
        """Initialize state before either event source starts."""
        self.commissioned = False
        self.commissioning = None
        self.session_active = False
        self.radar_ok = None
        self.occupancy = None


_state = _ProductState()


def render(color: tuple) -> None:
    """Drive the onboard pixel."""
    pixel[0] = color
    pixel.write()


def _pairing_color() -> tuple | None:
    """Return the colour describing where pairing currently stands, or None.

    None means pairing has nothing left to say and the product state owns the
    pixel.

    A closed window is the ambiguous one: it closes both when a commissioner
    takes it and when it simply runs out. The first is the middle of a healthy
    pairing, the second leaves the node advertising nothing — so the tracked
    session, not the closure, decides which colour it gets.
    """
    color = _COMMISSIONING_COLORS.get(_state.commissioning)
    if color is not None:
        return color
    if _state.session_active:
        return SESSION_COLOR
    if _state.commissioned:
        return None
    if _state.commissioning == matter.Commissioning.CLOSED:
        return STALLED_COLOR
    # Unpaired, and the stack has reported nothing yet.
    return BOOT_COLOR


def refresh() -> None:
    """Render the pixel color for the current product state.

    Pairing wins while it is in flight, on a commissioned node too: an owner
    adding a second controller wants to watch that, not the radar. Once the
    attempt settles, a paired node goes back to reporting radar health and
    occupancy. A missing radar still does not prevent commissioning.
    """
    color = _pairing_color()
    if color is None:
        if _state.radar_ok is False:
            color = RADAR_FAULT_COLOR
        else:
            color = CLEAR_COLOR if _state.occupancy is False else GREEN_COLOR
    render(color)


def _set_radar_ok(*, ok: bool) -> None:
    """Record a radar health transition and update the pixel."""
    if _state.radar_ok == ok:
        return
    _state.radar_ok = ok
    refresh()


def _publish_occupancy(*, occupied: bool) -> None:
    """Publish a changed occupancy value, leaving failures pending for retry."""
    try:
        occupancy.occupancy = 1 if occupied else 0
    except OSError as err:
        error("occupancy", str(err))
        return
    _state.occupancy = occupied
    refresh()


async def init_radar() -> LD2450:
    """Open the radar UART, retrying until a valid report arrives.

    Returns:
        A connected radar driver with its first report pending.
    """
    while True:
        try:
            radar = LD2450(bus_id=BOARD.uart_id, tx=BOARD.tx, rx=BOARD.rx)
            await radar.wait_ready()
        except (DeviceNotFoundError, OSError) as err:
            diag = "no_device" if isinstance(err, DeviceNotFoundError) else "init_err"
            emit({"diag": diag, "err": str(err)})
            _set_radar_ok(ok=False)
            await asyncio.sleep_ms(_RETRY_PAUSE_MS)
        else:
            _set_radar_ok(ok=True)
            emit({"diag": "radar_ok"})
            return radar


async def track_occupancy(radar: LD2450) -> None:
    """Publish occupancy changes before streaming each valid radar report.

    Args:
        radar: A driver that has completed startup.
    """
    last_stream_ms = None
    while True:
        try:
            targets = await radar.read_latest()
        except OSError as err:
            emit({"diag": "read_err", "err": str(err)})
            _set_radar_ok(ok=False)
            await asyncio.sleep_ms(_READ_ERR_PAUSE_MS)
            continue

        now_ms = time.ticks_ms()
        if targets is None:
            if _state.radar_ok is not False:
                emit({"diag": "report_timeout", "t": now_ms})
            _set_radar_ok(ok=False)
            continue

        targets = tuple(target for target in targets if _outside_dead_zone(target))
        _set_radar_ok(ok=True)
        occupied = bool(targets)
        if occupied != _state.occupancy:
            _publish_occupancy(occupied=occupied)
        stream_due = last_stream_ms is None or (
            time.ticks_diff(now_ms, last_stream_ms) >= _REPORT_STREAM_INTERVAL_MS
        )
        if stream_due:
            emit({"t": now_ms, "targets": [_target_dict(target) for target in targets]})
            last_stream_ms = now_ms


def _dashboard_address() -> tuple[str | None, OSError | None]:
    """Return the current address and any recoverable lookup error."""
    try:
        return node.network_address(), None
    except OSError as err:
        return None, err


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


def _report_dashboard_ready(address: str) -> None:
    """Emit the address of a running dashboard."""
    emit({"event": "dashboard", "state": "ready", "url": "http://" + address + "/"})


async def _start_dashboard(address: str) -> OSError | None:
    """Start and announce the dashboard, returning a recoverable failure."""
    try:
        await dashboard.start()
    except OSError as err:
        return err
    _report_dashboard_ready(address)
    return None


async def _reconcile_dashboard(address: str | None, *, reported_error: bool) -> tuple:
    """Reconcile one dashboard poll and return its next state.

    Args:
        address: Last address announced for the running listener.
        reported_error: Whether this failure period already emitted an error.

    Returns:
        Address, error-report flag, and delay before the next poll.
    """
    current, address_error = _dashboard_address()
    if address_error is not None:
        reported_error = _report_dashboard_error(address_error, already_reported=reported_error)
        return address, reported_error, _ADDRESS_POLL_MS
    if current is None:
        return None, False, _ADDRESS_POLL_MS
    if not dashboard.running:
        start_error = await _start_dashboard(current)
        if start_error is not None:
            reported_error = _report_dashboard_error(start_error, already_reported=reported_error)
            return address, reported_error, _DASHBOARD_RETRY_MS
        return current, False, _ADDRESS_POLL_MS
    if current != address:
        _report_dashboard_ready(current)
    return current, False, _ADDRESS_POLL_MS


async def serve_dashboard() -> None:
    """Keep the dashboard available once Matter networking has an address.

    Matter gets an undisturbed startup interval before diagnostics add another
    listener and network traffic. The listener then starts as soon as an address
    exists and binds every interface, so a later lease change needs no restart —
    only a fresh report of where to find the page.

    A dashboard that cannot be served is reported once per failure period and
    retried. It is a diagnostics view, and it must never take occupancy down.
    """
    address = None
    reported_error = False
    await asyncio.sleep_ms(_DASHBOARD_BOOT_DELAY_MS)

    while True:
        address, reported_error, delay_ms = await _reconcile_dashboard(
            address, reported_error=reported_error
        )
        await asyncio.sleep_ms(delay_ms)


async def main() -> None:
    """Serve the dashboard while the radar initializes and streams."""
    await asyncio.gather(serve_dashboard(), _track_radar())


async def _track_radar() -> None:
    """Initialize the radar and track occupancy until reset."""
    radar = await init_radar()
    try:
        await track_occupancy(radar)
    finally:
        radar.close()


def _target_dict(target: object) -> dict:
    """Convert one radar target to its raw dashboard fields."""
    return {
        "slot": target.slot,
        "x_mm": target.x_mm,
        "y_mm": target.y_mm,
        "speed_cm_s": target.speed_cm_s,
        "resolution_mm": target.resolution_mm,
    }


def _outside_dead_zone(target: object) -> bool:
    """Return whether a target lies beyond the sensor's near-field radius."""
    distance_squared = target.x_mm * target.x_mm + target.y_mm * target.y_mm
    return distance_squared >= _DEAD_ZONE_RADIUS_MM * _DEAD_ZONE_RADIUS_MM


def _on_commissioning(event: object) -> None:
    """Record one commissioning transition and update the pixel.

    A failure is rendered but not latched. The Matter package reopens a window
    whenever an unpaired node would otherwise stop advertising, so red is
    followed by purple within moments — and a red that stays red is then a
    genuine finding rather than a colour nothing was able to clear.

    Args:
        event: Commissioning event delivered by the Matter node.
    """
    state = event.state
    if state == matter.Commissioning.STARTED:
        _state.session_active = True
    elif state in (matter.Commissioning.COMPLETE, matter.Commissioning.FAILED):
        _state.session_active = False
    if state == matter.Commissioning.COMPLETE:
        _state.commissioned = True
    _state.commissioning = state
    refresh()


pixel = neopixel.NeoPixel(machine.Pin(BOARD.led_pin, machine.Pin.OUT), 1)
render(BOOT_COLOR)

# Routes only — serve_dashboard() binds the port once there is an address. The
# greeting is what the dashboard reads as "connected", the same line the host
# viz service sends when it opens the serial port.
dashboard = httpd.Server(port=_DASHBOARD_PORT)
dashboard.page(
    "/",
    dashboard_page.PAGE,
    content_type=dashboard_page.CONTENT_TYPE,
    encoding=dashboard_page.ENCODING,
)
reports = dashboard.stream(
    "/ws",
    greeting=ujson.dumps({"event": "connected", "port": f"ld2450 uart{BOARD.uart_id}"}),
)
add_sink(reports.send)

node = matter.Node()
occupancy = node.create_endpoint(matter.EndpointType.OCCUPANCY_SENSOR)
node.on_commissioning(_on_commissioning)
node.start()

# A commissioned board falls straight through to radar health and occupancy. An
# uncommissioned one shows whichever pairing state the transitions queued during
# startup left it in — normally purple, because the stack opens a window for a
# board that belongs to no fabric.
_state.commissioned = bool(node.fabrics()) or _state.commissioned
refresh()

asyncio.run(main())
