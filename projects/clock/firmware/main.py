"""MCU-micropython firmware for the clock project — display bring-up.

Drives the 16x32 LED matrix: two 8x32 MAX7219 panels daisy-chained on one SPI
bus (MCU -> top panel -> bottom panel, sharing 5 V/GND). The ``max7219`` driver
hides the cascade, so this firmware treats the matrix as one 16x32 surface and
just asks for a word per panel. The bring-up shows ``TOP`` on the top panel and
``bot`` on the bottom panel: a glance confirms both panels light, the chain order
(top word on the top panel), and the orientation (text right-side up). GPS is
omitted for now.
"""

import os
import time
from collections import namedtuple

import ujson

from boot_status_led import status
from max7219 import MAX7219

Board = namedtuple("Board", ("name", "spi_id", "sck", "mosi", "cs"))

_machine = os.uname().machine
if "ESP32S3" in _machine:
    BOARD = Board(name="ESP32-S3-Zero", spi_id=1, sck=5, mosi=6, cs=7)
elif "RP2350" in _machine:
    BOARD = Board(name="RP2350", spi_id=1, sck=10, mosi=11, cs=9)
else:
    BOARD = Board(name="RP2040-Zero", spi_id=1, sck=26, mosi=27, cs=28)

_BOOT_PAUSE_MS = 300
_INIT_ERR_PAUSE_MS = 1_000
_IDLE_SLEEP_MS = 500
_TOP_TEXT = "TOP"
_BOT_TEXT = "bot"


def emit(obj: dict) -> None:
    """Print one line of compact JSON to the serial port.

    All firmware output must go through this helper; raw ``print()`` calls
    elsewhere pollute the serial stream and are silently dropped by the viz
    JSON parser.
    """
    print(ujson.dumps(obj))


def run(display: object) -> None:
    """Render one word per panel, then idle while feeding the scheduler.

    Args:
        display: MAX7219 instance driving the 16x32 matrix.
    """
    status.streaming()
    display.show_lines(_TOP_TEXT, _BOT_TEXT)
    emit({"diag": "display_ready", "top": _TOP_TEXT, "bot": _BOT_TEXT})
    while True:
        time.sleep_ms(_IDLE_SLEEP_MS)
        display.reassert()


def main() -> None:
    """Run boot -> open the display -> show debug text. MicroPython entry point.

    LED sequence: white -> cyan (opening the SPI bus) -> green (running).
    On init failure: cyan -> magenta -> white (retry).
    """
    status.boot()
    time.sleep_ms(_BOOT_PAUSE_MS)
    status.i2c_init()
    while True:
        try:
            display = MAX7219(spi_id=BOARD.spi_id, sck=BOARD.sck, mosi=BOARD.mosi, cs=BOARD.cs)
        except Exception:  # noqa: BLE001
            status.init_err()
            emit({"diag": "init_err"})
            time.sleep_ms(_INIT_ERR_PAUSE_MS)
            continue
        run(display)


main()
