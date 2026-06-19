"""MCU-micropython firmware for the clock project — display bring-up.

Drives two independent 8x32 MAX7219 LED matrices (top and bottom, separate SPI
buses, shared 5 V/GND) to verify wiring: the top panel shows ``top 123`` and the
bottom panel shows ``456 bot``. GPS is omitted for now.
"""

import os
import time
from collections import namedtuple

import ujson

from boot_status_led import status
from max7219 import connect as display_connect

DisplayWiring = namedtuple("DisplayWiring", ("spi_id", "sck", "mosi", "cs"))
Board = namedtuple("Board", ("name", "status_led", "display_top", "display_bot"))

_machine = os.uname().machine
if "ESP32S3" in _machine:
    BOARD = Board(
        name="ESP32-S3-Zero",
        status_led=21,
        display_top=DisplayWiring(spi_id=1, sck=5, mosi=6, cs=7),
        display_bot=DisplayWiring(spi_id=2, sck=9, mosi=10, cs=11),
    )
elif "RP2350" in _machine:
    BOARD = Board(
        name="RP2350",
        status_led="LED",
        display_top=DisplayWiring(spi_id=1, sck=10, mosi=11, cs=9),
        display_bot=DisplayWiring(spi_id=0, sck=6, mosi=7, cs=8),
    )
else:
    BOARD = Board(
        name="RP2040-Zero",
        status_led=16,
        display_top=DisplayWiring(spi_id=1, sck=26, mosi=27, cs=28),
        display_bot=DisplayWiring(spi_id=0, sck=6, mosi=7, cs=8),
    )

_NUM_DISPLAY_MODULES = 4
_BOOT_PAUSE_MS = 300
_INIT_ERR_PAUSE_MS = 1_000
_IDLE_SLEEP_MS = 500
_TOP_TEXT = "top 123"
_BOT_TEXT = "456 bot"


def emit(obj: dict) -> None:
    """Print one line of compact JSON to the serial port.

    All firmware output must go through this helper; raw ``print()`` calls
    elsewhere pollute the serial stream and are silently dropped by the viz
    JSON parser.
    """
    print(ujson.dumps(obj))


def _open_display(wiring: DisplayWiring) -> object:
    """Open one MAX7219 chain from a ``DisplayWiring`` entry."""
    return display_connect(
        spi_id=wiring.spi_id,
        sck=wiring.sck,
        mosi=wiring.mosi,
        cs=wiring.cs,
        num_modules=_NUM_DISPLAY_MODULES,
    )


def run(display_top: object, display_bot: object) -> None:
    """Render the debug strings, then idle while feeding the scheduler.

    Args:
        display_top: MAX7219 instance driving the top 8x32 panel.
        display_bot: MAX7219 instance driving the bottom 8x32 panel.
    """
    status.streaming()
    display_top.show_text(_TOP_TEXT)
    display_bot.show_text(_BOT_TEXT)
    emit({"diag": "displays_ready", "top": _TOP_TEXT, "bot": _BOT_TEXT})
    while True:
        time.sleep_ms(_IDLE_SLEEP_MS)


def main() -> None:
    """Run boot → open both displays → show debug text. MicroPython entry point.

    LED sequence: white → cyan (opening SPI buses) → green (running).
    On init failure: cyan → magenta → white (retry).
    """
    status.boot()
    time.sleep_ms(_BOOT_PAUSE_MS)
    while True:
        status.i2c_init()
        try:
            display_top = _open_display(BOARD.display_top)
            display_bot = _open_display(BOARD.display_bot)
        except Exception:  # noqa: BLE001
            status.init_err()
            emit({"diag": "init_err"})
            time.sleep_ms(_INIT_ERR_PAUSE_MS)
            status.boot()
            continue
        run(display_top, display_bot)


main()
