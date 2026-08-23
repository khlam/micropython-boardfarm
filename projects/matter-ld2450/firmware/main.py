"""Publish HLK-LD2450 occupancy through Matter and stream radar diagnostics.

The newest complete radar report controls one read-only Occupancy Sensor
endpoint. Missing reports mark the radar unhealthy without clearing the last
published occupancy value.
"""

import asyncio
import os
import time
from collections import namedtuple

import machine
import neopixel
from micropython import const

import matter
from ld2450 import LD2450, DeviceNotFoundError
from matter.emit import emit, error

Board = namedtuple("Board", ("uart_id", "tx", "rx", "led_pin"))
_machine = os.uname().machine
if "ESP32S3" not in _machine:
    raise RuntimeError(f"unsupported board: {_machine}")
BOARD = Board(uart_id=1, tx=5, rx=6, led_pin=21)

_RETRY_PAUSE_MS = const(1_000)
_READ_ERR_PAUSE_MS = const(200)
# Near-field reports can collapse toward the origin as tracking ends. Ignore
# radius around the sensor so those artifacts cannot hold occupancy on.
_DEAD_ZONE_RADIUS_MM = const(10)

# One colour per state a node can be in before it is paired, because the
# failures worth catching are the ones where it stops advertising: a node nobody
# can reach has to look different from one waiting to be scanned. Amber is that
# state, so radar trouble takes yellow rather than sharing it.
BOOT_COLOR = (25, 25, 25)
GREEN_COLOR = (0, 25, 0)
WINDOW_COLOR = (25, 0, 25)
SESSION_COLOR = (0, 25, 25)
FAILED_COLOR = (25, 0, 0)
STALLED_COLOR = (25, 12, 0)
RADAR_FAULT_COLOR = (25, 25, 0)
CLEAR_COLOR = (0, 0, 25)

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
        emit({"t": now_ms, "targets": [_target_dict(target) for target in targets]})


async def main() -> None:
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
