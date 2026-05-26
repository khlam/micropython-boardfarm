"""MCU-micropython backend driving the RP2350 on-board green user LED via CYW43 GPIO0."""

from machine import Pin

# RP2350: on-board green user LED routed through the CYW43 chip's GPIO0,
# accessed in MicroPython as Pin("LED").
_led = Pin("LED", Pin.OUT)


def show(rgb: tuple[int, int, int]) -> None:
    """Map (r, g, b) to LED on/off.

    Green (streaming) maps to on; others map to off.
    """
    _led.value(1 if rgb == (0, 255, 0) else 0)
