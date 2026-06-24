"""MCU-micropython backend emulating an event-driven BOOT button on the RP2040-Zero.

BOOTSEL doubles as the QSPI flash CS line and has no GPIO interrupt, so a periodic
soft Timer polls rp2.bootsel_button() and fires the callback on the press edge.
"""

import micropython
import rp2
import utime
from machine import Timer
from micropython import const

_POLL_MS = const(30)
_DEBOUNCE_MS = const(150)

# Single mutable state dict so the handler can update the edge/debounce state
# without a `global` statement and without allocating. "timer" holds the Timer so
# it keeps firing; "callback" is the registered press handler.
_state = {"timer": None, "callback": None, "last_ms": 0, "was_down": False}


def on_press(callback: object) -> None:
    """Start a periodic soft Timer polling BOOTSEL for a debounced press edge."""
    _state["callback"] = callback
    timer = Timer()
    timer.init(period=_POLL_MS, mode=Timer.PERIODIC, callback=_poll)
    _state["timer"] = timer


def _poll(_timer: object) -> None:
    """Timer handler: detect a debounced press edge, defer the callback off-context.

    Allocation-free — only reads/writes pre-existing dict slots and schedules the
    pre-existing `_run` with a constant argument. Fires once per press edge, not
    while the button stays held.
    """
    down = rp2.bootsel_button() == 1
    if down and not _state["was_down"]:
        now = utime.ticks_ms()
        if utime.ticks_diff(now, _state["last_ms"]) >= _DEBOUNCE_MS:
            _state["last_ms"] = now
            micropython.schedule(_run, None)
    _state["was_down"] = down


def _run(_arg: object) -> None:
    """Soft-scheduled trampoline running the user callback outside timer context."""
    callback = _state["callback"]
    if callback is not None:
        callback()
