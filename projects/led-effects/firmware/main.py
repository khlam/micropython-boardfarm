"""MCU-micropython firmware entry point for the led-effects WS2812B demo.

Cycles through the four ws2812b animations — rainbow, hue rotation, breathing,
and colour fade — rendering each to the strip's data pin for a fixed run of
frames before advancing to the next. Pin assignments live in this module's
BOARD table (dispatched per chip by os.uname().machine); the Strip driver
takes the data pin as a constructor argument, so the package stays free of
board wiring and this firmware builds unchanged for RP2040, RP2350, and
ESP32-S3.
"""

import os
import time
from collections import namedtuple

import ujson

from boot_status_led import status
from ws2812b import Breathe, ColorFade, HueRotate, Rainbow, Strip

# Per-chip pin map — the authoritative wiring for this project, plain GPIO
# numbers. data_pin carries the external strip's data line, kept clear of the
# on-board WS2812 (boot status LED: GP16 on the Zeros, GPIO21 on ESP32-S3) so
# the on-board pixel is never first in the chain. Filled per chip by
# os.uname().machine dispatch at import.
Board = namedtuple("Board", ("name", "data_pin"))
_machine = os.uname().machine
if "ESP32S3" in _machine:
    BOARD = Board(name="ESP32-S3-Zero", data_pin=15)
elif "RP2350" in _machine:
    BOARD = Board(name="RP2350", data_pin=15)
else:
    BOARD = Board(name="RP2040-Zero", data_pin=15)

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
    strip = Strip(LED_COUNT, pin=BOARD.data_pin)
    status.streaming()
    run(strip, build_effects())


main()
