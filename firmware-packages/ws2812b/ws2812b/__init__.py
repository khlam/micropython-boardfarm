"""MCU-micropython WS2812B strip driver and parametric animation effects.

Public API:
    Strip(count)                 # chip-dispatched driver; render(frame)
    Rainbow(count, ...)          # full-spectrum sweep across the strip
    HueRotate(count, ...)        # continuous uniform hue shift
    Breathe(count, ...)          # sinusoidal brightness pulse of one colour
    ColorFade(count, ...)        # ping-pong interpolation between two colours
    hsv_to_rgb(h, s, v)          # 8-bit colour helper

Each effect's ``frame()`` returns the next ``list[(r, g, b)]``; pass it to
``Strip.render`` to drive the LEDs.
"""

from ws2812b.effects import Breathe, ColorFade, HueRotate, Rainbow, hsv_to_rgb
from ws2812b.strip import Strip

__all__ = ["Breathe", "ColorFade", "HueRotate", "Rainbow", "Strip", "hsv_to_rgb"]
