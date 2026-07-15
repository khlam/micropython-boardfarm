"""MCU-micropython firmware entry point for the led-effects WS2812B demo.

Cycles through the four ws2812b animations — rainbow, hue rotation, breathing,
and colour fade — rendering each to the board's WS2812B data pin for a fixed
run of frames before advancing to the next. Chip-agnostic: the data pin and
NeoPixel construction live in the ws2812b backend selected at import time, so
this firmware builds unchanged for RP2040, RP2350, and ESP32-S3.
"""

import time

import ujson

from boot_status_led import status
from ws2812b import Breathe, ColorFade, HueRotate, Rainbow, Strip

LED_COUNT = 20
FRAME_PERIOD_MS = 20  # ~50 fps render cadence
FRAMES_PER_EFFECT = 200  # frames shown before advancing to the next effect
_BOOT_PAUSE_MS = 300


def emit(obj: dict) -> None:
    """Print one line of compact JSON to the serial port.

    All firmware output must go through this helper; raw `print()` calls
    elsewhere pollute the serial stream and are silently dropped by the
    viz JSON parser.
    """
    print(ujson.dumps(obj))


def build_effects() -> tuple:
    """Return the demo's four effects, each fully parametrised at the call site.

    Returns:
        ``(name, effect)`` pairs in display order; `name` is emitted as a
        diagnostic when the effect becomes active.
    """
    return (
        ("rainbow", Rainbow(LED_COUNT, brightness=0.3, step=0.01)),
        ("hue_rotate", HueRotate(LED_COUNT, brightness=0.3, speed=0.005)),
        ("breathe", Breathe(LED_COUNT, color=(0, 128, 255), brightness=0.4, period=80)),
        (
            "color_fade",
            ColorFade(LED_COUNT, start=(255, 0, 0), end=(0, 0, 255), brightness=0.3, step=0.01),
        ),
    )


def run(strip: Strip, effects: tuple) -> None:
    """Cycle `effects` forever, rendering FRAMES_PER_EFFECT frames of each."""
    while True:
        for name, effect in effects:
            emit({"effect": name})
            for _ in range(FRAMES_PER_EFFECT):
                strip.render(effect.frame())
                time.sleep_ms(FRAME_PERIOD_MS)


def main() -> None:
    """Run boot → build strip + effects → cycle. MicroPython entry point."""
    status.boot()
    time.sleep_ms(_BOOT_PAUSE_MS)
    strip = Strip(LED_COUNT)
    status.streaming()
    run(strip, build_effects())


main()
