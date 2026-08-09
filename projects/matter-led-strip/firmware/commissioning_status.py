"""Commissioning-status light show for the strip: boot/ready/pairing/failure colours.

`main.py` owns the strip hardware and the two real colour-setting paths
(`set_color`, `on_remote_write`); this module owns only the decision of what
the strip should show while ESP-Matter is starting up or commissioning, plus
the shared stamp-ordered render gate both sides funnel through so a status
transition and a controller write can never race each other out of order.

This module never touches `machine`/`neopixel` directly and has no reference
to `main.py`'s globals, so the strip's render callback and the Matter node/
endpoint it needs are handed in explicitly:

    commissioning_status.bind_render(render)      # as soon as `strip` exists
    ...
    commissioning_status.bind_node(node, endpoint) # as soon as they exist
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

# Injected dependencies. List cells so bind_render()/bind_node() can set them
# without `global`, matching the mutable-cell idiom used for the state below.
_render = [None]
_node = [None]
_endpoint = [None]

# Tick the current colour was commanded on. Ordering only, never written to
# flash. A list cell so `show()` below can update it without `global`.
_stamp = [0]

# Last colour actually rendered, regardless of who commanded it. Distinct from
# `_stamp`: two calls can legitimately share a stamp (the post-start
# reconciliation reuses the pre-start boot stamp) without that meaning the
# colour changed, so this stops the second call from repeating a hardware
# write `show()` already made.
_last_shown = [None]

# Commissioning events can be delivered while Node.start() is still returning.
# Mutable cells let the callback record that state without publishing through
# an endpoint whose owning node is not marked started yet.
_commissioned = [False]
_commissioning_failed = [False]
_last_commissioning_state = [None]
_last_commissioning_stamp = [0]
_pending_commissioned_off = [None]


def bind_render(render: object) -> None:
    """Wire up the hardware write callback. Call as soon as the strip exists.

    Args:
        render: Callable accepting one RGB byte triple and driving the strip.
    """
    _render[0] = render


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


def show(color: tuple, stamp: int) -> None:
    """Render a colour unless a newer one was already commanded or it repeats.

    Callbacks can run out of order, so an older decision could otherwise
    overwrite a newer one. Comparing stamps stops that. Comparing against the
    last colour actually rendered stops a same-stamp repeat (the post-start
    reconciliation call) from bit-banging the strip twice for one colour.

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
    if color == _last_shown[0]:
        return
    _last_shown[0] = color
    _render[0](color)  # ty: ignore[call-non-callable]


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
        _show_status(FAILED_COLOR, commissioning_stamp)
        return
    state = _last_commissioning_state[0]
    color = _COMMISSIONING_COLORS.get(state)
    if color is not None:
        _show_status(color, commissioning_stamp)
    elif state == matter.Commissioning.CLOSED:
        _restore_after_window(commissioning_stamp)
    elif _commissioned[0]:
        _show_status(matter_to_triple(_endpoint[0]), startup_stamp)
    else:
        _show_status(READY_COLOR, startup_stamp)


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
        _show_status(matter_to_triple(_endpoint[0]), stamp)
    else:
        _show_status(READY_COLOR, stamp)
