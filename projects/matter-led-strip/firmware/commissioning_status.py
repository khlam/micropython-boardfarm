"""Commissioning-status light show for the onboard and external strip LEDs.

Boot/ready/pairing/failure colours on the onboard WS2812, real colour changes
on the external strip.

`main.py` owns both pieces of hardware and the two real colour-setting paths
(`set_color`, `on_remote_write`); this module owns only the decision of what
each LED should show while ESP-Matter is starting up or commissioning, plus
two independent stamp-ordered render gates -- one per LED, so a status
transition can never race another status transition, and a controller write
can never race another controller write, out of order on the hardware each
one owns.

This module never touches `machine`/`neopixel` directly and has no reference
to `main.py`'s globals, so the render callbacks and the Matter node/endpoint
it needs are handed in explicitly:

    commissioning_status.bind_status_render(render_status)  # onboard WS2812
    commissioning_status.bind_strip_render(render)           # external strip
    ...
    commissioning_status.bind_node(node, endpoint)           # as soon as they exist
"""

import time

from color import matter_to_triple

import matter

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

# Injected dependencies. List cells so the bind_*()/bind_node() calls can set
# them without `global`, matching the mutable-cell idiom used for the state
# below.
_status_render = [None]
_strip_render = [None]
_node = [None]
_endpoint = [None]

# Tick the current colour was commanded on, one per gate since the two LEDs
# are driven independently. Ordering only, never written to flash. List cells
# so show_status()/show_strip() below can update them without `global`.
_status_stamp = [0]
_strip_stamp = [0]

# Last colour actually rendered on each LED, regardless of who commanded it.
# Distinct from the stamps above: two calls can legitimately share a stamp
# (the post-start reconciliation reuses the pre-start boot stamp) without that
# meaning the colour changed, so this stops the second call from repeating a
# hardware write its gate already made.
_last_status_shown = [None]
_last_strip_shown = [None]

# Commissioning events can be delivered while Node.start() is still returning.
# Mutable cells let the callback record that state without publishing through
# an endpoint whose owning node is not marked started yet.
_commissioned = [False]
_commissioning_failed = [False]
_last_commissioning_state = [None]
_last_commissioning_stamp = [0]
_pending_commissioned_off = [None]


def bind_status_render(render: object) -> None:
    """Wire up the onboard status LED's write callback.

    Args:
        render: Callable accepting one RGB byte triple and driving the
            onboard WS2812.
    """
    _status_render[0] = render


def bind_strip_render(render: object) -> None:
    """Wire up the external strip's write callback. Call as soon as `strip` exists.

    Args:
        render: Callable accepting one RGB byte triple and driving the strip.
    """
    _strip_render[0] = render


def bind_node(node: object, endpoint: object) -> None:
    """Wire up the Matter node/endpoint. Call as soon as they're constructed.

    Args:
        node: The project's `matter.Node`.
        endpoint: The project's colour-light `matter.Endpoint`.
    """
    _node[0] = node
    _endpoint[0] = endpoint


def is_commissioned() -> bool:
    """Return whether this boot has observed the board as commissioned."""
    return _commissioned[0]


def _gate(
    color: tuple, stamp: int, stamp_cell: list, last_shown_cell: list, render: object
) -> None:
    """Render on one LED unless a newer command already won or this one repeats.

    Shared by `show_status` and `show_strip`, each passing its own cells so
    the two LEDs are gated independently -- callbacks can run out of order,
    and a same-stamp repeat (the post-start reconciliation call) must not
    bit-bang the LED twice.

    Args:
        color: RGB byte triple to render.
        stamp: Tick the colour was commanded on, for ordering against gate.
        stamp_cell: This LED's one-element `[stamp]` ordering cell.
        last_shown_cell: This LED's one-element `[colour]` de-dup cell.
        render: Callable accepting one RGB byte triple and driving the LED.
    """
    if time.ticks_diff(stamp, stamp_cell[0]) < 0:
        return
    stamp_cell[0] = stamp
    if color == last_shown_cell[0]:
        return
    last_shown_cell[0] = color
    render(color)  # ty: ignore[call-non-callable]


def show_status(color: tuple, stamp: int) -> None:
    """Render a status colour on the onboard LED unless a newer one already won."""
    if _commissioning_failed[0] and color != FAILED_COLOR:
        return
    _gate(color, stamp, _status_stamp, _last_status_shown, _status_render[0])


def show_strip(color: tuple, stamp: int) -> None:
    """Render a real colour on the external strip unless a newer one already won."""
    _gate(color, stamp, _strip_stamp, _last_strip_shown, _strip_render[0])


def on_commissioning(event: object) -> None:
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
        show_status(FAILED_COLOR, stamp)
        return
    if state == matter.Commissioning.COMPLETE:
        _commissioning_failed[0] = False
        _commissioned[0] = True
        _finish_commissioning(stamp)
        return
    if not _commissioning_failed[0]:
        _show_commissioning_color(state, stamp)


def show_post_start_state(*, has_fabric: bool, startup_stamp: int) -> None:
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
        show_status(FAILED_COLOR, commissioning_stamp)
        return
    if _show_commissioning_color(_last_commissioning_state[0], commissioning_stamp):
        return
    if _commissioned[0]:
        show_strip(matter_to_triple(_endpoint[0]), startup_stamp)
    else:
        show_status(READY_COLOR, startup_stamp)


def _show_commissioning_color(state: object, stamp: int) -> bool:
    """Show `state`'s status colour, or restore after a closed window.

    Shared by `on_commissioning` and `show_post_start_state`: the same state
    maps to the same action whether handled live or reconciled after
    `Node.start()` returns.

    Args:
        state: The commissioning state to render, or `None`.
        stamp: Tick the state was observed on, for gate ordering.

    Returns:
        Whether `state` was recognised and handled.
    """
    color = _COMMISSIONING_COLORS.get(state)
    if color is not None:
        show_status(color, stamp)
        return True
    if state == matter.Commissioning.CLOSED:
        _restore_after_window(stamp)
        return True
    return False


def _finish_commissioning(stamp: int) -> None:
    """Turn the newly commissioned accessory off locally and in Matter.

    A completion event may arrive before :meth:`matter.Node.start` returns. In
    that case the strip can turn off immediately, while publication remains
    pending until the node reports that it has started.
    """
    _pending_commissioned_off[0] = stamp
    show_strip(OFF_COLOR, stamp)
    node = _node[0]
    if not node.started:
        return
    _endpoint[0].on = False
    _pending_commissioned_off[0] = None


def _restore_after_window(stamp: int) -> None:
    """Restore application state after a commissioning window closes.

    Args:
        stamp: Tick captured when the window closed.
    """
    node = _node[0]
    if not node.started:
        return
    if _commissioned[0]:
        show_strip(matter_to_triple(_endpoint[0]), stamp)
    else:
        show_status(READY_COLOR, stamp)
