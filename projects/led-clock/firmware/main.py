"""MCU-micropython firmware entry point for the led-clock seven-segment digit.

Drives one seven-segment digit made of WS2812B LEDs chained from a single data
pin, counting 0 to 9 in green, one step per second, forever. Wiring — the data
pin, the order the chain visits the segments, and LEDs per segment — lives in
this module's constants. RP2040-Zero is the only supported board.
"""

import time
from collections import namedtuple

import ujson
from machine import Pin
from neopixel import NeoPixel
from seven_segment import DIGIT_SEGMENTS, digit_frame

from boot_status_led import status

# The authoritative wiring for this project, plain GPIO numbers. data_pin
# carries the digit's chain, kept clear of the on-board WS2812 boot status LED
# on GP16 so that pixel is never part of the digit.
Board = namedtuple("Board", ("name", "data_pin"))
BOARD = Board(name="RP2040-Zero", data_pin=15)

# Segments in the order the data line visits them, starting at DIN, in the
# board's segment letters (see seven_segment: b is the top bar).
CHAIN_ORDER = "abcdefg"
LEDS_PER_SEGMENT = 2
GREEN = (0, 64, 0)  # ~25% brightness
OFF = (0, 0, 0)
STEP_PERIOD_MS = 1000


def emit(obj: dict) -> None:
    """Print one line of compact JSON to the serial port.

    All firmware output must go through this helper; raw `print()` calls
    elsewhere pollute the serial stream.
    """
    print(ujson.dumps(obj))


def count(np: NeoPixel, frames: list) -> None:
    """Show each digit's frame in turn, one per STEP_PERIOD_MS, forever.

    Args:
        np: The digit's LED chain.
        frames: One precomputed frame per digit, indexed by the digit.
    """
    while True:
        for digit, frame in enumerate(frames):
            for i, rgb in enumerate(frame):
                np[i] = rgb
            np.write()
            emit({"digit": digit})
            time.sleep_ms(STEP_PERIOD_MS)


def main() -> None:
    """Run boot → build chain + frames → count. MicroPython entry point."""
    status.boot()
    np = NeoPixel(Pin(BOARD.data_pin, Pin.OUT), len(CHAIN_ORDER) * LEDS_PER_SEGMENT)
    frames = [
        digit_frame(
            digit,
            chain_order=CHAIN_ORDER,
            leds_per_segment=LEDS_PER_SEGMENT,
            on=GREEN,
            off=OFF,
        )
        for digit in range(len(DIGIT_SEGMENTS))
    ]
    status.streaming()
    count(np, frames)


main()
