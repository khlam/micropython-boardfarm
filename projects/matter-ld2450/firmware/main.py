"""Expose an HLK-LD2450 radar through ESP-Matter as an Occupancy Sensor.

Definitions first, boot sequence at the bottom. The Matter node is built and
started synchronously, because `Node.start()` blocks while ESP-Matter comes up;
only then does `asyncio.run(main())` take over for the radar, whose driver is
woken by a UART receive-idle interrupt. The node's event drain rides the
MicroPython scheduler, so it interleaves with the event loop.

The radar reports targets; Matter wants a single occupied/clear bit. This file
owns that translation, along with the pixel and the board wiring. Nothing here
knows how the radar frames a report, and nothing in `matter/` knows a radar
exists.

Calls into `matter.Node`, `Node.start`, or an `Endpoint` attribute leave this
file for compiled code: `matter/` (Python) calls the `_matter` C module, which
calls the C++ bridge in `native/src/`, which drives ESP-Matter/CHIP. Full
call-path diagrams: `firmware-packages/matter/ARCHITECTURE.md`.
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

# Pin map for this board. ``uart_id`` selects the peripheral, ``tx`` connects to
# radar RX, ``rx`` connects to radar TX, and ``led_pin`` drives the onboard
# WS2812. Only ESP32-S3 is supported, so any other chip is a build error.
Board = namedtuple("Board", ("name", "uart_id", "tx", "rx", "led_pin", "pixel_count"))
_machine = os.uname().machine
if "ESP32S3" not in _machine:
    raise RuntimeError(f"unsupported board: {_machine}")
BOARD = Board(name="ESP32-S3-Zero", uart_id=1, tx=5, rx=6, led_pin=21, pixel_count=1)

# The LD2450 drops a motionless person for several reports at a time, so the
# occupied state is held past the last sighting rather than tracking each
# report. Fifteen seconds rides out those gaps without feeling stuck on.
_OCCUPANCY_HOLD_MS = const(15_000)
_RETRY_PAUSE_MS = const(1_000)
_READ_ERR_PAUSE_MS = const(200)

BOOT_COLOR = (25, 25, 25)
READY_COLOR = (0, 25, 0)
WINDOW_COLOR = (25, 0, 25)
SESSION_COLOR = (0, 25, 25)
FAILED_COLOR = (25, 0, 0)
RADAR_FAULT_COLOR = (25, 12, 0)
OCCUPIED_COLOR = (0, 25, 0)
OFF_COLOR = (0, 0, 0)

_COMMISSIONING_COLORS = {
    matter.Commissioning.STARTED: SESSION_COLOR,
    matter.Commissioning.OPENED: WINDOW_COLOR,
}

# Tick the current colour was commanded on. Ordering only, never written to
# flash. A list cell so `show()` below can update it without `global`.
_stamp = [0]

# Commissioning events can be delivered while Node.start() is still returning.
# Mutable cells let the callback record that state without publishing through
# an endpoint whose owning node is not marked started yet.
_commissioned = [False]
_commissioning_failed = [False]
_last_commissioning_state = [None]

# Product state the pixel renders once pairing is settled. Radar health and
# occupancy start as None rather than False: "not decided yet" makes their
# first outcomes trigger the state transitions that report and render them.
_radar_ok = [None]
_occupied = [None]


def render(color: tuple) -> None:
    """Drive the pixel. Every hardware touch in this project is these two lines."""
    pixel[0] = color
    pixel.write()


def show(color: tuple, stamp: int) -> None:
    """Render a colour unless a newer one was already commanded.

    Commissioning callbacks and the radar loop both command colours and can run
    out of order, so an older decision could otherwise overwrite a newer one.
    Comparing stamps stops that.

    Args:
        color: Red, green, and blue channel values in the range 0-255.
        stamp: `time.ticks_ms()` reading from when the colour was commanded.
            Equal stamps render, so the boot baseline still shows.
    """
    if _commissioning_failed[0] and color != FAILED_COLOR:
        return
    if time.ticks_diff(stamp, _stamp[0]) < 0:
        return
    _stamp[0] = stamp
    render(color)


def current_color() -> tuple:
    """Return the colour the board's present state calls for.

    One decision point for every caller, so the pixel never depends on which
    event happened to fire last. Commissioning failure stays sticky; otherwise
    a silent radar outranks pairing and occupancy because a stale "clear" is
    indistinguishable from a disconnected sensor.
    """
    if _commissioning_failed[0]:
        return FAILED_COLOR
    if _radar_ok[0] is False:
        return RADAR_FAULT_COLOR
    color = _COMMISSIONING_COLORS.get(_last_commissioning_state[0])
    if color is not None:
        return color
    if not _commissioned[0]:
        return READY_COLOR
    return OCCUPIED_COLOR if _occupied[0] else OFF_COLOR


def refresh(stamp: int) -> None:
    """Re-render whatever the current state calls for.

    Args:
        stamp: Tick captured when the state that prompted this changed.
    """
    show(current_color(), stamp)


async def init_radar() -> LD2450:
    """Open the radar UART, retrying until the radar sends a valid report.

    Retrying yields to the event loop, so a board with no radar attached still
    commissions and stays reachable.

    Returns:
        A connected radar driver with its first report ready to read.
    """
    while True:
        try:
            radar = LD2450(bus_id=BOARD.uart_id, tx=BOARD.tx, rx=BOARD.rx)
            await radar.wait_ready()
        except (DeviceNotFoundError, OSError):
            _set_radar_ok(time.ticks_ms(), ok=False)
            await asyncio.sleep_ms(_RETRY_PAUSE_MS)
        else:
            _set_radar_ok(time.ticks_ms(), ok=True)
            return radar


async def track_occupancy(radar: LD2450) -> None:
    """Publish occupancy to Matter whenever it changes, and only then.

    `read_latest()` returns targets, an empty tuple for a report with none, or
    ``None`` when no complete report arrived within 500 ms. Only a real target
    refreshes the hold timer, so a radar that goes quiet falls back to clear
    rather than latching occupied forever.

    Args:
        radar: A driver already through `wait_ready()`.
    """
    last_seen_ms = None
    while True:
        try:
            targets = await radar.read_latest()
        except OSError:
            _set_radar_ok(time.ticks_ms(), ok=False)
            await asyncio.sleep_ms(_READ_ERR_PAUSE_MS)
            continue

        now_ms = time.ticks_ms()
        _set_radar_ok(now_ms, ok=True)
        if targets:
            last_seen_ms = now_ms
        occupied = (
            last_seen_ms is not None and time.ticks_diff(now_ms, last_seen_ms) < _OCCUPANCY_HOLD_MS
        )
        if occupied == _occupied[0]:
            continue

        try:
            # Endpoint.publish -> _matter.attribute_publish -> request.cpp
            # matter_attribute_publish: a bounded round trip onto the CHIP task.
            # Occupancy is a Matter bitmap, so it travels as 0 or 1, not a bool.
            endpoint.occupancy = 1 if occupied else 0
        except OSError:
            # Leave the recorded state alone so the next pass retries.
            continue
        _occupied[0] = occupied
        refresh(now_ms)


async def main() -> None:
    """Bring the radar up, then track occupancy until the board is reset."""
    radar = await init_radar()
    try:
        await track_occupancy(radar)
    finally:
        radar.close()


def _set_radar_ok(stamp: int, *, ok: bool) -> None:
    """Record radar health, re-rendering only when it actually flips.

    Reports arrive several times a second, so refreshing unconditionally would
    rewrite the pixel — and advance the stamp every other state change is
    ordered against — on every pass.

    Args:
        stamp: Tick captured when the change was observed.
        ok: True once a report parses, False when the read fails.
    """
    if _radar_ok[0] == ok:
        return
    _radar_ok[0] = ok
    refresh(stamp)


def _on_commissioning(event: object) -> None:
    """Record one commissioning transition and re-render.

    Args:
        event: :class:`matter.CommissioningEvent` delivered by the node.
    """
    stamp = time.ticks_ms()
    state = event.state
    if state == matter.Commissioning.FAILED:
        _commissioning_failed[0] = True
    elif state == matter.Commissioning.COMPLETE:
        _commissioning_failed[0] = False
        _commissioned[0] = True
    _last_commissioning_state[0] = state
    refresh(stamp)


pixel = neopixel.NeoPixel(machine.Pin(BOARD.led_pin, machine.Pin.OUT), BOARD.pixel_count)

# White is the only state known before the stack starts. Later commissioning
# events and radar readings replace it with their own newer stamps.
_startup_stamp = time.ticks_ms()
_stamp[0] = _startup_stamp
show(BOOT_COLOR, _startup_stamp)

# Node() -> matter/node.py Node.__init__ -> _matter.node_create() ->
# stack.cpp matter_node_create(). Runs directly on this task -- there is no CHIP
# task yet to schedule onto.
node = matter.Node()

# No initial state passed: the native endpoint constructor owns the unoccupied
# starting value, and a pre-start write would pin it on every boot.
endpoint = node.create_endpoint(matter.EndpointType.OCCUPANCY_SENSOR)

# Occupancy is read-only to controllers, so no on_write callback is registered.
# Queued transitions may be delivered before start() returns; the callback only
# records state and re-renders, both safe before the node reports started.
node.on_commissioning(_on_commissioning)

# start() -> _matter.start() -> stack.cpp matter_stack_start(): the CHIP task
# comes up here, and the call blocks while endpoints are restored. It has to
# finish before the event loop exists.
node.start()

_commissioned[0] = bool(node.fabrics()) or _commissioned[0]
refresh(_startup_stamp)

asyncio.run(main())
