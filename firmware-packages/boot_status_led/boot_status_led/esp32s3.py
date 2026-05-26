"""MCU-micropython backend driving the ESP32-S3-Zero on-board WS2812 on GPIO21."""

from machine import Pin
from neopixel import NeoPixel

_led = NeoPixel(Pin(21, Pin.OUT), 1)
BRIGHTNESS = 0.1  # reduce brightness


def show(rgb: tuple[int, int, int]) -> None:
    """Drive WS2812 to (r, g, b) tuple, scaled by BRIGHTNESS."""
    _led[0] = tuple(int(c * BRIGHTNESS) for c in rgb)
    _led.write()
