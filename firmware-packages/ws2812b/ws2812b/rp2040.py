"""MCU-micropython WS2812B backend for the RP2040-Zero — strip data line on GP15."""

from machine import Pin
from neopixel import NeoPixel

# GP15 carries the external strip's data line, kept clear of the on-board WS2812
# (boot status LED) on GP16.
DATA_PIN = 15


def pixels(count: int) -> NeoPixel:
    """Construct a ``count``-LED WS2812B strip on this board's data pin."""
    return NeoPixel(Pin(DATA_PIN, Pin.OUT), count)
