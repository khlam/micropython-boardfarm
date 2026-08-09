"""Commissioning-status light show for the onboard and external strip LEDs.

Boot/ready/pairing/failure colours and patterns appear on the onboard WS2812
and reserve the external strip while ESP-Matter is starting or commissioning.
Once released, the project pattern renderer owns the strip again.

`main.py` owns both pieces of hardware; this module owns only the decision of
what each LED should show during a status overlay, plus two independent
stamp-ordered render gates -- one per LED -- so status transitions cannot
reach either piece of hardware out of order.

This module never touches `neopixel` or claims a GPIO pin directly -- `main.py`
still owns every pin assignment -- and has no reference to `main.py`'s
globals, so the render callbacks and the Matter node/endpoint it needs are
handed in explicitly:

    commissioning_status.bind_status_render(render_status)  # onboard WS2812
    commissioning_status.bind_strip_render(render)           # external strip
    ...
    commissioning_status.bind_node(node, endpoint)           # as soon as they exist
    commissioning_status.start_animator()                    # arms the pattern ticker

It does own ESP32 hardware timer 0, with a soft callback dispatched through
the MicroPython scheduler, to drive the failure blink pattern below.
"""

import time

import machine
import micropython
from color import matter_to_triple

import matter

BOOT_COLOR = (25, 25, 25)
CYAN_COLOR = (0, 25, 25)
COMMISSIONED_COLOR = (0, 25, 0)
FAILED_COLOR = (25, 0, 0)
OFF_COLOR = (0, 0, 0)

# Animation tick rate and blink period. Chosen so the period length is an
# exact multiple of the tick, keeping blink edges crisp.
_TICK_MS = micropython.const(50)
_BLINK_PERIOD_MS = micropython.const(3000)
_BLINK_ON_MS = micropython.const(500)

_COMMISSIONING_PATTERNS = {
    matter.Commissioning.STARTED: (("steady", CYAN_COLOR), ("steady", CYAN_COLOR)),
    matter.Commissioning.OPENED: (("steady", CYAN_COLOR), ("steady", CYAN_COLOR)),
}
_READY_PATTERN = (("steady", CYAN_COLOR), ("steady", CYAN_COLOR))

# Injected dependencies. List cells so the bind_*()/bind_node() calls can set
# them without `global`, matching the mutable-cell idiom used for the state
# below.
_status_render = [None]
_strip_render = [None]
_strip_release = [None]
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
_strip_reserved = [True]

# The active (mode, color) pattern per LED, or None while that LED is
# steady. Both share one stamp: every frame of the current animation carries
# the stamp of the state transition that started it, so a genuinely newer
# transition -- which advances the gate's stamp cell -- automatically
# outraces any stale in-flight frame without extra bookkeeping.
_onboard_anim = [None]
_ring_anim = [None]
_anim_stamp = [0]
_timer = [None]


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


def bind_strip_release(callback: object) -> None:
    """Wire the callback that restores application output after an overlay.

    Args:
        callback: Callable restarting the application-owned strip renderer.
    """
    _strip_release[0] = callback


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


def strip_available() -> bool:
    """Return whether application output currently owns the external strip."""
    return not _strip_reserved[0]


def start_animator() -> None:
    """Arm the periodic ticker that drives the failure blink pattern.

    Call once during boot, after both render callbacks are bound. ESP32's
    MicroPython port exposes only physical timers, numbered from zero; its
    default soft callback is made explicit so NeoPixel writes run on the VM
    task rather than in interrupt context. The `Timer` is kept in a module
    cell so it isn't garbage-collected once armed.
    """
    _timer[0] = machine.Timer(0)
    _timer[0].init(
        mode=machine.Timer.PERIODIC,
        period=_TICK_MS,
        callback=_render_tick,
        hard=False,
    )


def _frame_color(mode: str, color: tuple, elapsed_ms: int) -> tuple:
    """Compute one animation frame for `mode` at `elapsed_ms` into its cycle.

    Args:
        mode: `"steady"` or `"blink"`.
        color: The pattern's peak colour.
        elapsed_ms: Milliseconds since the pattern started.

    Returns:
        The RGB byte triple to render this frame.
    """
    if mode == "blink":
        return color if elapsed_ms % _BLINK_PERIOD_MS < _BLINK_ON_MS else OFF_COLOR
    return color


def _apply(onboard: tuple, ring: tuple, stamp: int) -> None:
    """Render or animate both LEDs for one state transition.

    The single choke point for every commissioning-state transition: renders
    frame 0 immediately (so there's no flash-of-black waiting for the next
    tick), then arms or clears the per-LED animation cells so `_render_tick`
    picks up the blink pattern on subsequent ticks.

    Args:
        onboard: `(mode, color)` for the onboard LED.
        ring: `(mode, color)` for the external strip.
        stamp: Tick this transition was commanded on.
    """
    _anim_stamp[0] = stamp
    _onboard_anim[0] = onboard if onboard[0] != "steady" else None
    _ring_anim[0] = ring if ring[0] != "steady" else None
    show_status(_frame_color(onboard[0], onboard[1], 0), stamp)
    show_strip(_frame_color(ring[0], ring[1], 0), stamp)


def _render_tick(_arg: object) -> None:
    """Render the current animation frame from the timer's soft callback.

    Args:
        _arg: The firing `machine.Timer`. Unused.
    """
    if _onboard_anim[0] is None and _ring_anim[0] is None:
        return
    elapsed_ms = time.ticks_diff(time.ticks_ms(), _anim_stamp[0])
    onboard = _onboard_anim[0]
    if onboard is not None:
        show_status(_frame_color(onboard[0], onboard[1], elapsed_ms), _anim_stamp[0])
    ring = _ring_anim[0]
    if ring is not None:
        show_strip(_frame_color(ring[0], ring[1], elapsed_ms), _anim_stamp[0])


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
    """Render a status overlay on the strip unless a newer one already won."""
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
        _reserve_strip()
        _apply(("steady", FAILED_COLOR), ("blink", FAILED_COLOR), stamp)
        return
    if state == matter.Commissioning.COMPLETE:
        _commissioning_failed[0] = False
        _commissioned[0] = True
        _finish_commissioning(stamp)
        return
    if not _commissioning_failed[0]:
        _show_commissioning_pattern(state, stamp)


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
        _reserve_strip()
        _apply(("steady", FAILED_COLOR), ("blink", FAILED_COLOR), commissioning_stamp)
        return
    if _show_commissioning_pattern(_last_commissioning_state[0], commissioning_stamp):
        return
    if _commissioned[0]:
        _apply(
            ("steady", COMMISSIONED_COLOR),
            ("steady", matter_to_triple(_endpoint[0])),
            startup_stamp,
        )
        _release_strip()
    else:
        _reserve_strip()
        _apply(*_READY_PATTERN, startup_stamp)


def _show_commissioning_pattern(state: object, stamp: int) -> bool:
    """Show `state`'s status pattern, or restore after a closed window.

    Shared by `on_commissioning` and `show_post_start_state`: the same state
    maps to the same action whether handled live or reconciled after
    `Node.start()` returns.

    Args:
        state: The commissioning state to render, or `None`.
        stamp: Tick the state was observed on, for gate ordering.

    Returns:
        Whether `state` was recognised and handled.
    """
    pair = _COMMISSIONING_PATTERNS.get(state)
    if pair is not None:
        _reserve_strip()
        _apply(*pair, stamp)
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
    _reserve_strip()
    _pending_commissioned_off[0] = stamp
    _apply(("steady", COMMISSIONED_COLOR), ("steady", OFF_COLOR), stamp)
    node = _node[0]
    if not node.started:
        return
    _endpoint[0].on = False
    _pending_commissioned_off[0] = None
    _release_strip()


def _restore_after_window(stamp: int) -> None:
    """Restore application state after a commissioning window closes.

    Args:
        stamp: Tick captured when the window closed.
    """
    node = _node[0]
    if not node.started:
        return
    if _commissioned[0]:
        _apply(("steady", COMMISSIONED_COLOR), ("steady", matter_to_triple(_endpoint[0])), stamp)
        _release_strip()
    else:
        _reserve_strip()
        _apply(*_READY_PATTERN, stamp)


def _reserve_strip() -> None:
    """Give the commissioning overlay exclusive access to the strip."""
    if not _strip_reserved[0]:
        # Application patterns bypass the overlay's de-duplication cache, so
        # the first overlay frame must be treated as new after every handoff.
        _last_strip_shown[0] = None
    _strip_reserved[0] = True


def _release_strip() -> None:
    """Return strip ownership to the application and restart its renderer."""
    if not _strip_reserved[0]:
        return
    _strip_reserved[0] = False
    callback = _strip_release[0]
    if callback is not None:
        callback()
