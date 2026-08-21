"""Drive one Matter occupancy endpoint on a fixed timer, with no radar attached.

Bring-up firmware for one question: does Apple Home track this device's sensing
state at all, and which of Home's "Motion" and "Occupancy" room categories does
the endpoint land in? The radar is deliberately absent, so nothing but the
timer below can move an attribute — a tile that never changes is a controller
or schema problem, not a sensor problem.

A single Occupancy Sensor endpoint is published, declaring PIR as its sensing
modality. Matter has no separate motion-sensor device type, so the declared
modality is the only lever a controller could sort it by, and which category
Home files it under is exactly what this firmware is here to find out. It flips
every minute, so a stuck value cannot be mistaken for a working one.

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
from matter.emit import emit

# Pin map for this board. Only the pixel is left — this firmware never opens the
# radar UART. Only ESP32-S3 is supported, so any other chip is a build error.
Board = namedtuple("Board", ("name", "led_pin", "pixel_count"))
_machine = os.uname().machine
if "ESP32S3" not in _machine:
    raise RuntimeError(f"unsupported board: {_machine}")
BOARD = Board(name="ESP32-S3-Zero", led_pin=21, pixel_count=1)
emit({"event": "debug", "component": "boot", "state": "imports_ready", "machine": _machine})

# One minute per phase: long enough to read a Home tile without racing it, short
# enough that a stalled toggle shows up within a couple of minutes.
_TOGGLE_PERIOD_MS = const(60_000)

BOOT_COLOR = (25, 25, 25)
READY_COLOR = (0, 25, 0)
WINDOW_COLOR = (25, 0, 25)
SESSION_COLOR = (0, 25, 25)
FAILED_COLOR = (25, 0, 0)
OCCUPIED_COLOR = (0, 25, 0)
CLEAR_COLOR = (0, 0, 25)

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

# Which half of the cycle the endpoint is in, or None until the first phase is
# published.
_occupied = [None]


def render(color: tuple) -> None:
    """Drive the pixel. Every hardware touch in this project is these two lines."""
    emit({"event": "debug", "component": "pixel", "state": "buffer", "rgb": color})
    pixel[0] = color
    emit({"event": "debug", "component": "pixel", "state": "write"})
    pixel.write()
    emit({"event": "debug", "component": "pixel", "state": "write_complete"})


def show(color: tuple, stamp: int) -> None:
    """Render a colour unless a newer one was already commanded.

    Commissioning callbacks and the toggle timer both command colours and can
    run out of order, so an older decision could otherwise overwrite a newer
    one. Comparing stamps stops that.

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
    event happened to fire last. Commissioning failure stays sticky, and active
    pairing outranks the toggle phase, which has sixty seconds to be read and
    the pairing colours do not.
    """
    if _commissioning_failed[0]:
        return FAILED_COLOR
    color = _COMMISSIONING_COLORS.get(_last_commissioning_state[0])
    if color is not None:
        return color
    if not _commissioned[0] or _occupied[0] is None:
        return READY_COLOR
    return OCCUPIED_COLOR if _occupied[0] else CLEAR_COLOR


def refresh(stamp: int) -> None:
    """Re-render whatever the current state calls for.

    Args:
        stamp: Tick captured when the state that prompted this changed.
    """
    show(current_color(), stamp)


async def toggle_forever() -> None:
    """Publish alternating phases to the endpoint once a minute, until reset.

    The first phase is occupied and is published immediately, so a controller
    that subscribes right after commissioning sees a deliberate value rather
    than the constructor's zero.
    """
    emit({"event": "debug", "component": "toggle", "state": "tracking"})
    occupied = True
    while True:
        _apply_phase(occupied=occupied)
        await asyncio.sleep_ms(_TOGGLE_PERIOD_MS)
        occupied = not occupied


def _apply_phase(*, occupied: bool) -> None:
    """Publish one phase to the endpoint and re-render the pixel.

    A failed publish is reported and left behind rather than retried here: the
    timer is the only clock this firmware has, and repeating a phase to catch a
    straggler would break the alternation Home is being read for.

    Args:
        occupied: Value to publish on the Occupancy attribute.
    """
    stamp = time.ticks_ms()
    if _publish(on=occupied):
        _occupied[0] = occupied
    refresh(stamp)

    # The dashboard keys its box off this component. No targets stream in this
    # firmware, so the toggle is what keeps the box moving.
    emit(
        {
            "event": "debug",
            "component": "occupancy",
            "state": "occupied" if occupied else "clear",
        }
    )


def _publish(*, on: bool) -> bool:
    """Publish the endpoint's Occupancy attribute and report what happened.

    Args:
        on: True to publish occupied.

    Returns:
        True when the value reached ESP-Matter.
    """
    try:
        # Endpoint.publish -> _matter.attribute_publish -> request.cpp
        # matter_attribute_publish: a bounded round trip onto the CHIP task.
        # Occupancy is a Matter bitmap, so it travels as 0 or 1, not a bool.
        occupancy.occupancy = 1 if on else 0
    except OSError as err:
        emit(
            {
                "event": "debug",
                "component": "toggle",
                "state": "publish_failed",
                "message": str(err),
            }
        )
        return False
    emit(
        {
            "event": "debug",
            "component": "toggle",
            "endpoint_id": occupancy.id,
            "state": "on" if on else "off",
        }
    )
    return True


def _on_commissioning(event: object) -> None:
    """Record one commissioning transition and re-render.

    Args:
        event: :class:`matter.CommissioningEvent` delivered by the node.
    """
    stamp = time.ticks_ms()
    state = event.state
    emit({"event": "debug", "component": "commissioning", "state": state})
    if state == matter.Commissioning.FAILED:
        _commissioning_failed[0] = True
    elif state == matter.Commissioning.COMPLETE:
        _commissioning_failed[0] = False
        _commissioned[0] = True
    _last_commissioning_state[0] = state
    refresh(stamp)


emit(
    {
        "event": "debug",
        "component": "pixel",
        "state": "construct",
        "pin": BOARD.led_pin,
        "count": BOARD.pixel_count,
    }
)
pixel = neopixel.NeoPixel(machine.Pin(BOARD.led_pin, machine.Pin.OUT), BOARD.pixel_count)
emit({"event": "debug", "component": "pixel", "state": "constructed"})

# White is the only state known before the stack starts. Later commissioning
# events and toggle phases replace it with their own newer stamps.
_startup_stamp = time.ticks_ms()
_stamp[0] = _startup_stamp
show(BOOT_COLOR, _startup_stamp)

# Node() -> matter/node.py Node.__init__ -> _matter.node_create() ->
# stack.cpp matter_node_create(). Runs directly on this task -- there is no CHIP
# task yet to schedule onto.
emit({"event": "debug", "component": "matter", "state": "node_create"})
node = matter.Node()
emit({"event": "debug", "component": "matter", "state": "node_created"})

# No initial state passed: the endpoint starts unoccupied from its native
# constructor, and `toggle_forever()` publishes the real first phase as soon as
# the event loop starts.
emit({"event": "debug", "component": "matter", "state": "endpoint_create"})
occupancy = node.create_endpoint(matter.EndpointType.OCCUPANCY_SENSOR)
emit(
    {
        "event": "debug",
        "component": "matter",
        "state": "endpoint_created",
        "endpoint_id": occupancy.id,
    }
)

# Occupancy is read-only to controllers, so no on_write callback is registered.
# Queued transitions may be delivered before start() returns; the callback only
# records state and re-renders, both safe before the node reports started.
node.on_commissioning(_on_commissioning)
emit({"event": "debug", "component": "matter", "state": "callback_ready"})

# start() -> _matter.start() -> stack.cpp matter_stack_start(): the CHIP task
# comes up here, and the call blocks while endpoints are restored. It has to
# finish before the event loop exists.
emit({"event": "debug", "component": "matter", "state": "start"})
node.start()
emit({"event": "debug", "component": "matter", "state": "started"})

emit({"event": "debug", "component": "matter", "state": "fabrics_read"})
_fabrics = node.fabrics()
emit(
    {
        "event": "debug",
        "component": "matter",
        "state": "fabrics_ready",
        "count": len(_fabrics),
    }
)
_commissioned[0] = bool(_fabrics) or _commissioned[0]
refresh(_startup_stamp)

emit({"event": "debug", "component": "boot", "state": "event_loop_start"})
asyncio.run(toggle_forever())
