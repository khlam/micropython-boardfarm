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
from max7219 import connect as display_connect

DisplayWiring = namedtuple("DisplayWiring", ("spi_id", "sck", "mosi", "cs"))
Board = namedtuple("Board", ("name", "status_led", "display"))

_machine = os.uname().machine
if "ESP32S3" in _machine:
    BOARD = Board(
        name="ESP32-S3-Zero",
        status_led=21,
        display=DisplayWiring(spi_id=1, sck=5, mosi=6, cs=7),
    )
elif "RP2350" in _machine:
    BOARD = Board(
        name="RP2350",
        status_led="LED",
        display=DisplayWiring(spi_id=1, sck=10, mosi=11, cs=9),
    )
else:
    BOARD = Board(
        name="RP2040-Zero",
        status_led=16,
        display=DisplayWiring(spi_id=1, sck=26, mosi=27, cs=28),
    )

_BOOT_PAUSE_MS = 300
_INIT_ERR_PAUSE_MS = 1_000
_IDLE_SLEEP_MS = 500
# One word per 8x32 panel: "TOP" on the top panel, "bot" on the bottom. If they
# read swapped, the daisy-chain order is reversed; if upside down or mirrored,
# flip _FLIP_Y / _MIRROR_X in the max7219 driver.
_TOP_TEXT = "TOP"
_BOT_TEXT = "bot"


def emit(obj: dict) -> None:
    """Print one line of compact JSON to the serial port.

    All firmware output must go through this helper; raw ``print()`` calls
    elsewhere pollute the serial stream and are silently dropped by the viz
    JSON parser.
    """
    print(ujson.dumps(obj))


def _open_display(wiring: DisplayWiring) -> object:
    """Open the daisy-chained 16x32 MAX7219 display from a ``DisplayWiring`` entry."""
    return display_connect(
        spi_id=wiring.spi_id,
        sck=wiring.sck,
        mosi=wiring.mosi,
        cs=wiring.cs,
    )


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


def main() -> None:
    """Run boot -> open the display -> show debug text. MicroPython entry point.

    LED sequence: white -> cyan (opening the SPI bus) -> green (running).
    On init failure: cyan -> magenta -> white (retry).
    """
    status.boot()
    time.sleep_ms(_BOOT_PAUSE_MS)
    while True:
        status.i2c_init()
        try:
            display = _open_display(BOARD.display)
        except Exception:  # noqa: BLE001
            status.init_err()
            emit({"diag": "init_err"})
            time.sleep_ms(_INIT_ERR_PAUSE_MS)
            status.boot()
            continue
        run(display)


main()
