"""MCU MicroPython firmware for the clock project.

Reads UTC date/time and longitude from an ATGM336H GPS over UART, derives a
fixed local offset from longitude, sets the onboard RTC, and drives the modular
display cycle on the 16x32 MAX7219 matrix.
"""

import os
import random
import time
from collections import namedtuple

from boot_button import button
from machine import RTC

from atgm336h import GPS
from boot_status_led import status
from clock_cycle import POLL_SLEEP_MS, DisplayCycle
from clock_sync import emit, sync_from_line
from max7219 import MAX7219

UartWiring = namedtuple("UartWiring", ("bus_id", "tx", "rx"))
PixelSurface = namedtuple("PixelSurface", ("width_pixels", "height_pixels", "brightness"))
DisplayWiring = namedtuple(
    "DisplayWiring",
    (
        "spi_id",
        "sck",
        "mosi",
        "cs",
        "surface",
    ),
)
Board = namedtuple("Board", ("name", "uart", "display"))

_DISPLAY_SURFACE = PixelSurface(width_pixels=32, height_pixels=16, brightness=0.1)

_machine = os.uname().machine
if "ESP32S3" in _machine:
    BOARD = Board(
        name="ESP32-S3-Zero",
        uart=UartWiring(bus_id=1, tx=13, rx=12),
        display=DisplayWiring(
            spi_id=1,
            sck=5,
            mosi=6,
            cs=7,
            surface=_DISPLAY_SURFACE,
        ),
    )
elif "RP2350" in _machine:
    BOARD = Board(
        name="RP2350",
        uart=UartWiring(bus_id=1, tx=4, rx=5),
        display=DisplayWiring(
            spi_id=1,
            sck=10,
            mosi=11,
            cs=9,
            surface=_DISPLAY_SURFACE,
        ),
    )
else:
    BOARD = Board(
        name="RP2040-Zero",
        uart=UartWiring(bus_id=0, tx=0, rx=1),
        display=DisplayWiring(
            spi_id=1,
            sck=26,
            mosi=27,
            cs=28,
            surface=_DISPLAY_SURFACE,
        ),
    )

_BOOT_PAUSE_MS = 300
_INIT_ERR_PAUSE_MS = 1_000


def run(gps: object, display: object, rtc: object) -> None:
    """Read GPS sentences, keep the RTC current, and drive the display.

    Args:
        gps: Object with ``readline() -> str | None``.
        display: Object exposing ``show(frame)``.
        rtc: ``machine.RTC`` instance used as the clock source between fixes.
    """
    status.streaming()
    sync_state = {"synced": False}
    display_cycle = DisplayCycle(
        display,
        rtc,
        clock=time,
        rng=random,
    )
    while True:
        try:
            sync_from_line(gps.readline(), rtc, sync_state, emit, time)
            display_cycle.tick(synced=sync_state.get("synced", False))
            time.sleep_ms(POLL_SLEEP_MS)
        except Exception:  # noqa: BLE001
            status.read_err()
            emit({"diag": "read_err"})
            time.sleep_ms(POLL_SLEEP_MS)
            status.streaming()


def main() -> None:
    """Run boot -> GPS/display init -> live clock loop. MicroPython entry point.

    LED sequence: white -> cyan (opening buses) -> green (running).
    On init failure: cyan -> magenta -> white (retry).
    """
    status.boot()
    time.sleep_ms(_BOOT_PAUSE_MS)

    def _on_button_press() -> None:
        pass  # TODO: define BOOT-button press behavior

    button.on_press(_on_button_press)
    while True:
        status.i2c_init()
        try:
            surface = BOARD.display.surface
            display = MAX7219(
                spi_id=BOARD.display.spi_id,
                sck=BOARD.display.sck,
                mosi=BOARD.display.mosi,
                cs=BOARD.display.cs,
                width_pixels=surface.width_pixels,
                height_pixels=surface.height_pixels,
                brightness=surface.brightness,
            )
            gps = GPS(bus_id=BOARD.uart.bus_id, tx=BOARD.uart.tx, rx=BOARD.uart.rx)
            rtc = RTC()
        except Exception:  # noqa: BLE001
            status.init_err()
            emit({"diag": "init_err"})
            time.sleep_ms(_INIT_ERR_PAUSE_MS)
            status.boot()
            continue
        run(gps, display, rtc)


main()
