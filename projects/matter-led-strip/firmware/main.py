"""Expose an external WS2812B strip through ESP-Matter as one Extended Color Light.

Definitions first, boot sequence at the bottom. The module runs once at boot,
then drops to the REPL with `strip`, `node`, `endpoint`, and the functions
below still in scope, so a serial session can drive the light and administer
the node.

Calls into `matter.Node`, `Node.start`, or an `Endpoint` attribute leave this
file for compiled code that drives ESP-Matter/CHIP; see
`firmware-packages/matter/ARCHITECTURE.md` for the call-path diagrams.
"""

import os
import time
from collections import namedtuple

import machine
import neopixel
from color import matter_to_triple, publish_triple

import matter

# data_pin is the external strip's data line, kept separate from the onboard
# WS2812. Only ESP32-S3 is supported, so any other chip is a build error.
Board = namedtuple("Board", ("name", "data_pin"))
_machine = os.uname().machine
if "ESP32S3" not in _machine:
    raise RuntimeError(f"unsupported board: {_machine}")
BOARD = Board(name="ESP32-S3-Zero", data_pin=7)

LED_COUNT = 20

BOOT_COLOR = (25, 25, 25)
READY_COLOR = (0, 25, 0)
WINDOW_COLOR = (25, 0, 25)
SESSION_COLOR = (0, 25, 25)
FAILED_COLOR = (25, 0, 0)
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
_last_commissioning_stamp = [0]
_pending_commissioned_off = [None]

# Last colour on_remote_write actually rendered
_last_remote_color = [None]


def render(color: tuple) -> None:
    """Drive the strip. Every hardware touch in this project is these two lines."""
    for i in range(LED_COUNT):
        strip[i] = color
    strip.write()


def show(color: tuple, stamp: int) -> None:
    """Render a colour unless a newer one was already commanded.

    Callbacks can run out of order, so an older decision could otherwise
    overwrite a newer one. Comparing stamps stops that.

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


def set_color(color: tuple) -> None:
    """Show a colour locally, then publish it to Matter.

    Colour is published before power, so a controller never briefly sees the
    old colour lit.

    Args:
        color: Red, green, and blue channel values in the range 0-255.
    """
    show(color, time.ticks_ms())
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


def _show_status(color: tuple, stamp: int) -> None:
    """Render a status colour using the transition's original ordering stamp.

    Args:
        color: Static project-owned status colour.
        stamp: Tick captured when the transition occurred.
    """
    show(color, stamp)


def _finish_commissioning(stamp: int) -> None:
    """Turn the newly commissioned accessory off locally and in Matter.

    A completion event may arrive before :meth:`matter.Node.start` returns. In
    that case the strip can turn off immediately, while publication remains
    pending until the node reports that it has started.
    """
    _pending_commissioned_off[0] = stamp
    _show_status(OFF_COLOR, stamp)
    if not node.started:
        return
    endpoint.on = False
    _pending_commissioned_off[0] = None


def _restore_after_window(stamp: int) -> None:
    """Restore application state after a commissioning window closes.

    Args:
        stamp: Tick captured when the window closed.
    """
    if not node.started:
        return
    if _commissioned[0]:
        _show_status(matter_to_triple(endpoint), stamp)
    else:
        _show_status(READY_COLOR, stamp)


def _on_commissioning(event: object) -> None:
    """Render one commissioning transition without letting failure be overwritten.

    Args:
        event: :class:`matter.CommissioningEvent` delivered by the node.
    """
    stamp = time.ticks_ms()
    state = event.state
    _last_commissioning_state[0] = state
    _last_commissioning_stamp[0] = stamp
    if state == matter.Commissioning.FAILED:
        _commissioning_failed[0] = True
        _show_status(FAILED_COLOR, stamp)
        return
    if state == matter.Commissioning.COMPLETE:
        _commissioning_failed[0] = False
        _commissioned[0] = True
        _finish_commissioning(stamp)
        return
    if _commissioning_failed[0]:
        return
    color = _COMMISSIONING_COLORS.get(state)
    if color is not None:
        _show_status(color, stamp)
    elif state == matter.Commissioning.CLOSED:
        _restore_after_window(stamp)


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
    commissioning_stamp = _last_commissioning_stamp[0]
    if _commissioning_failed[0]:
        _show_status(FAILED_COLOR, commissioning_stamp)
        return
    state = _last_commissioning_state[0]
    color = _COMMISSIONING_COLORS.get(state)
    if color is not None:
        _show_status(color, commissioning_stamp)
    elif state == matter.Commissioning.CLOSED:
        _restore_after_window(commissioning_stamp)
    elif _commissioned[0]:
        _show_status(matter_to_triple(endpoint), startup_stamp)
    else:
        _show_status(READY_COLOR, startup_stamp)


strip = neopixel.NeoPixel(machine.Pin(BOARD.data_pin, machine.Pin.OUT), LED_COUNT)

# White is the only state known before the stack starts. Later commissioning
# events and restored controller state replace it with their own newer stamps.
_startup_stamp = time.ticks_ms()
_stamp[0] = _startup_stamp
show(BOOT_COLOR, _startup_stamp)

node = matter.Node()

# No initial state passed: every attribute here is one a controller owns, and
# pinning one now would overwrite what persistence is about to restore.
endpoint = node.create_endpoint(matter.EndpointType.EXTENDED_COLOR_LIGHT)

endpoint.on_write(on_remote_write)

# Queued transitions may be delivered before start() returns. The callback
# records any action that requires a started node and _show_post_start_state()
# completes it below.
node.on_commissioning(_on_commissioning)

node.start()

# A commissioned board restores its last controller-owned colour, applied
# uniformly across the strip. An uncommissioned board settles on green unless
# a queued window/session event selected purple or cyan.
_show_post_start_state(has_fabric=bool(node.fabrics()), startup_stamp=_startup_stamp)
