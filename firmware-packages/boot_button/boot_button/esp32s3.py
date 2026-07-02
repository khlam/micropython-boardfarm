"""MCU-micropython backend exposing the ESP32-S3-Zero BOOT button on GPIO0 via a hardware IRQ."""

import micropython
import utime
from machine import Pin
from micropython import const

_DEBOUNCE_MS = const(150)

# Single mutable state dict so the handler can update the debounce timestamp
# without a `global` statement and without allocating. "button" holds the Pin so
# its IRQ isn't garbage-collected; "callback" is the registered press handler.
_state = {"button": None, "callback": None, "last_ms": 0}


def on_press(callback: object) -> None:
    """Wire a falling-edge IRQ on GPIO0 to a debounced, deferred callback."""
    _state["callback"] = callback
    button = Pin(0, Pin.IN, Pin.PULL_UP)
    button.irq(trigger=Pin.IRQ_FALLING, handler=_isr)
    _state["button"] = button


def _isr(_pin: object) -> None:
    """Hard-IRQ handler: debounce, then defer the callback off interrupt context.

    Allocation-free — only reads/writes pre-existing dict slots and schedules the
    pre-existing `_run` with a constant argument.
    """
    now = utime.ticks_ms()
    if utime.ticks_diff(now, _state["last_ms"]) < _DEBOUNCE_MS:
        return
    _state["last_ms"] = now
    micropython.schedule(_run, None)


def _run(_arg: object) -> None:
    """Soft-scheduled trampoline running the user callback outside IRQ context."""
    callback = _state["callback"]
    if callback is not None:
        callback()
