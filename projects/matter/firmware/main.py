"""Expose the ESP32-S3-Zero onboard WS2812 through ESP-Matter.

Definitions first, boot sequence at the bottom. The module runs once at boot,
then drops to the REPL with `pixel`, `node`, `endpoint`, and the functions
below still in scope, so a serial session can drive the light and administer
the node.

Calls into `matter.Node`, `Node.start`, or an `Endpoint` attribute leave this
file for compiled code: `matter/` (Python) calls the `_matter` C module
(`native/micropython/matter_module.c`), which calls the C++ bridge in
`native/src/`, which drives ESP-Matter/CHIP. Comments below name the native
file each call lands in next. Full call-path diagrams:
`firmware-packages/matter/ARCHITECTURE.md`.
"""

import os
import time
from collections import namedtuple

import machine
import neopixel
from color import matter_to_triple, publish_triple

import matter

# Pin map for this board. led_pin drives the onboard WS2812. Only ESP32-S3 is
# supported, so any other chip is a build error, not a fallback case.
Board = namedtuple("Board", ("name", "led_pin", "pixel_count"))
_machine = os.uname().machine
if "ESP32S3" not in _machine:
    raise RuntimeError(f"unsupported board: {_machine}")
BOARD = Board(name="ESP32-S3-Zero", led_pin=21, pixel_count=1)

# One colour per state a node can be in before it is paired, because the
# failures worth catching are the ones where it stops advertising: a node nobody
# can reach has to look different from one waiting to be scanned.
BOOT_COLOR = (25, 25, 25)
WINDOW_COLOR = (25, 0, 25)
SESSION_COLOR = (0, 25, 25)
FAILED_COLOR = (25, 0, 0)
STALLED_COLOR = (25, 12, 0)
OFF_COLOR = (0, 0, 0)

# Tick the current colour was commanded on. Ordering only, never written to
# flash. A list cell so `show()` below can update it without `global`.
_stamp = [0]

# Commissioning events can be delivered while Node.start() is still returning.
# Mutable cells let the callback record that state without publishing through
# an endpoint whose owning node is not marked started yet.
_commissioned = [False]
_commissioning_state = [None]
_session_active = [False]
_last_commissioning_stamp = [0]
_pending_commissioned_off = [None]

# Last colour on_remote_write actually rendered
_last_remote_color = [None]


def render(color: tuple) -> None:
    """Drive the strip. Every hardware touch in this project is these two lines."""
    pixel[0] = color
    pixel.write()


def show(color: tuple, stamp: int) -> None:
    """Render a colour unless a newer one was already commanded.

    Callbacks can run out of order, so an older decision could otherwise
    overwrite a newer one. Comparing stamps stops that.

    Args:
        color: Red, green, and blue channel values in the range 0-255.
        stamp: `time.ticks_ms()` reading from when the colour was commanded.
            Equal stamps render, so the boot baseline still shows.
    """
    if time.ticks_diff(stamp, _stamp[0]) < 0:
        return
    _stamp[0] = stamp
    render(color)


def set_color(color: tuple) -> None:
    """Show a colour locally, then publish it to Matter.

    Colour is published before power, so a controller never briefly sees the
    old colour lit.

    Args:
        color: Red, green, and blue channel values in the range 0-255.
    """
    show(color, time.ticks_ms())
    # Below: Endpoint.publish -> _matter.attribute_publish -> request.cpp
    # matter_attribute_publish -- a bounded round trip onto the CHIP task
    # (ARCHITECTURE.md "A local change going out").
    publish_triple(endpoint, color)
    lit = endpoint.level != 0
    if endpoint.on != lit:
        endpoint.on = lit


def on_remote_write(_event: object) -> None:
    """Show the colour a controller just wrote, unless it repeats the last one shown.

    The event only names the one attribute that changed, so the full colour
    is read back from the endpoint instead of computed from the event. Comparing
    against the last colour actually rendered drops a repeat before it
    reaches the bit-banged NeoPixel write.

    Args:
        _event: Unused. Only wakes this callback.
    """
    color = matter_to_triple(endpoint)
    if color == _last_remote_color[0]:
        return
    _last_remote_color[0] = color
    show(color, time.ticks_ms())


def _pairing_color() -> tuple:
    """Return the colour describing where pairing currently stands.

    A closed window is the ambiguous one: it closes both when a commissioner
    takes it and when it simply runs out. The first is the middle of a healthy
    pairing, the second leaves the node advertising nothing — so the tracked
    session, not the closure, decides which colour it gets.
    """
    state = _commissioning_state[0]
    if state == matter.Commissioning.FAILED:
        return FAILED_COLOR
    if state == matter.Commissioning.STARTED:
        return SESSION_COLOR
    if state == matter.Commissioning.OPENED:
        return WINDOW_COLOR
    if _session_active[0]:
        return SESSION_COLOR
    if state == matter.Commissioning.CLOSED:
        return STALLED_COLOR
    return BOOT_COLOR


def _show_state(stamp: int) -> None:
    """Render whichever of pairing state or controller-owned colour applies.

    Pairing wins while it is in flight, on a commissioned node too: an owner
    adding a second controller wants to watch that, not the light. Once the
    attempt settles, a paired node goes back to showing its colour.

    Args:
        stamp: Tick captured when the state being rendered was decided.
    """
    pairing = _session_active[0] or _commissioning_state[0] in (
        matter.Commissioning.OPENED,
        matter.Commissioning.STARTED,
        matter.Commissioning.FAILED,
    )
    if _commissioned[0] and not pairing:
        show(matter_to_triple(endpoint), stamp)
        return
    show(_pairing_color(), stamp)


def _finish_commissioning(stamp: int) -> None:
    """Turn the newly commissioned accessory off locally and in Matter.

    A completion event may arrive before :meth:`matter.Node.start` returns. In
    that case the pixel can turn off immediately, while publication remains
    pending until the node reports that it has started.
    """
    _pending_commissioned_off[0] = stamp
    show(OFF_COLOR, stamp)
    if not node.started:
        return
    endpoint.on = False
    _pending_commissioned_off[0] = None


def _on_commissioning(event: object) -> None:
    """Record one commissioning transition and render the state it leaves.

    A failure is rendered but not latched. The Matter package reopens a window
    whenever an unpaired node would otherwise stop advertising, so red is
    followed by purple within moments — and a red that stays red is then a
    genuine finding rather than a colour nothing was able to clear.

    Args:
        event: :class:`matter.CommissioningEvent` delivered by the node.
    """
    stamp = time.ticks_ms()
    state = event.state
    _commissioning_state[0] = state
    _last_commissioning_stamp[0] = stamp
    if state == matter.Commissioning.STARTED:
        _session_active[0] = True
    elif state in (matter.Commissioning.COMPLETE, matter.Commissioning.FAILED):
        _session_active[0] = False
    if state == matter.Commissioning.COMPLETE:
        _commissioned[0] = True
        _finish_commissioning(stamp)
        return
    _show_state(stamp)


def _show_post_start_state(*, has_fabric: bool, startup_stamp: int) -> None:
    """Reconcile queued commissioning events with restored Matter state.

    Args:
        has_fabric: Whether the started node belongs to at least one fabric.
        startup_stamp: Tick captured before startup, keeping restoration older
            than any controller or commissioning event delivered during it.
    """
    _commissioned[0] = has_fabric or _commissioned[0]
    pending_stamp = _pending_commissioned_off[0]
    if pending_stamp is not None:
        _finish_commissioning(pending_stamp)
        return
    if _commissioning_state[0] is None:
        _show_state(startup_stamp)
        return
    _show_state(_last_commissioning_stamp[0])


pixel = neopixel.NeoPixel(machine.Pin(BOARD.led_pin, machine.Pin.OUT), BOARD.pixel_count)

# White is the only state known before the stack starts. Later commissioning
# events and restored controller state replace it with their own newer stamps.
_startup_stamp = time.ticks_ms()
_stamp[0] = _startup_stamp
show(BOOT_COLOR, _startup_stamp)

# Node() -> matter/node.py Node.__init__ -> _matter.node_create() ->
# stack.cpp matter_node_create() -> esp_matter::node::create(). Runs directly
# on this task -- there's no CHIP task yet to schedule onto (ARCHITECTURE.md
# "Boot").
node = matter.Node()

# create_endpoint() crosses into stack.cpp the same way: matter_endpoint_create(),
# then matter_attribute_set_initial() for each attribute named in initial.
#
# No initial state passed: every attribute here is one a controller owns, and
# pinning one now would overwrite what persistence is about to restore.
endpoint = node.create_endpoint(matter.EndpointType.EXTENDED_COLOR_LIGHT)

# on_write() just stores this callback on the Python Endpoint
# (matter/endpoint.py) -- nothing native happens here. It fires later from
# Node._drain (ARCHITECTURE.md "A controller write coming in").
endpoint.on_write(on_remote_write)

# Queued transitions may be delivered before start() returns. The callback
# records any action that requires a started node and _show_post_start_state()
# completes it below.
node.on_commissioning(_on_commissioning)

# start() -> _matter.start() -> stack.cpp matter_stack_start() ->
# esp_matter::start(): the CHIP task comes up here. After this line, native
# calls schedule a Request onto that task and block on a semaphore
# (native/src/request.cpp) instead of running directly.
node.start()

# A commissioned board restores its last controller-owned colour. An
# uncommissioned board shows whichever pairing state the transitions queued
# during startup left it in — normally purple, because the stack opens a window
# for a board that belongs to no fabric. fabrics() takes the same bounded
# request.cpp round trip as the attribute writes above.
_show_post_start_state(has_fabric=bool(node.fabrics()), startup_stamp=_startup_stamp)
