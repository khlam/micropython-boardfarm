"""MCU-micropython board-agnostic BOOT button as an event-driven component.

Selects a chip-specific backend at import time and exposes one uniform callback
API. The project registers a callback once and never polls:

    from boot_button import button
    button.on_press(handle_press)

The ESP32-S3-Zero drives the callback from a true GPIO0 hardware interrupt; the
RP2040-Zero and RP2350 emulate the same event from a periodic soft timer that
polls `rp2.bootsel_button()`, because BOOTSEL is the QSPI flash CS line and has
no GPIO interrupt. All backends debounce and defer the callback off interrupt
context, so callers see a single clean press notification either way.
"""

import os

# Pick the chip-specific backend at import time.
_machine = os.uname().machine
if "ESP32S3" in _machine:
    from boot_button.esp32s3 import on_press as _on_press
elif "RP2350" in _machine:
    from boot_button.rp2350 import on_press as _on_press
else:
    from boot_button.rp2040 import on_press as _on_press


def on_press(callback: object) -> None:
    """Register `callback`, invoked once per debounced BOOT-button press.

    The callback runs in scheduler context (via `micropython.schedule`), not in
    the interrupt/timer handler, so it may allocate and do non-trivial work.
    """
    _on_press(callback)
