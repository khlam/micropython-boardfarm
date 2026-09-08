"""MCU-micropython board-agnostic BOOT button as an event-driven component.

Selects a chip-specific backend at import time and exposes one uniform callback
API. The project registers a callback once and never polls:

    from boot_button import button
    button.on_press(handle_press)

A backend only detects the raw press edge: the ESP32-S3-Zero from a true GPIO0
hardware interrupt, the RP2040-Zero and RP2350 from a periodic soft timer that
polls `rp2.bootsel_button()`, because BOOTSEL is the QSPI flash CS line and has
no GPIO interrupt. Debouncing and deferring the callback off interrupt context
are the same on every chip, so they live here and every backend inherits them.
"""

import os

import micropython
import utime
from micropython import const

# Pick the chip-specific edge detector at import time. Both RP chips read BOOTSEL
# the same way, so they share one backend rather than each getting a named module.
_machine = os.uname().machine
if "ESP32S3" in _machine:
    from boot_button.esp32s3 import watch_edges as _watch_edges
else:
    from boot_button.bootsel import watch_edges as _watch_edges

_DEBOUNCE_MS = const(150)

# Single mutable state dict so the edge handler can update the debounce timestamp
# without a `global` statement and without allocating.
_state = {"callback": None, "last_ms": 0}


def on_press(callback: object) -> None:
    """Register `callback`, invoked once per debounced BOOT-button press.

    The callback runs in scheduler context (via `micropython.schedule`), not in
    the interrupt/timer handler, so it may allocate and do non-trivial work.
    """
    _state["callback"] = callback
    _watch_edges(_on_edge)


def _on_edge() -> None:
    """Backend press edge: debounce, then defer the callback off interrupt context.

    Runs in interrupt/timer context, so it stays allocation-free — it only
    reads/writes pre-existing dict slots and schedules the pre-existing `_run`
    with a constant argument.
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
