"""MCU MicroPython firmware for the clock project.

Reads UTC date/time and position from an ATGM336H GPS over UART, derives a
local timezone offset, sets the onboard RTC, and drives the modular
display cycle on the 16x32 MAX7219 matrix.
"""

import os
import random
import time
from collections import namedtuple

from boot_button import button
from clock_hardware import ClockHardware
from clock_runtime import ClockRuntime
from machine import RTC

from atgm336h import GPS
from boot_status_led import status
from clock_cycle import POLL_SLEEP_MS
from clock_sync import emit
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

_SURFACE = PixelSurface(width_pixels=32, height_pixels=16, brightness=0.1)

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
            surface=_SURFACE,
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
            surface=_SURFACE,
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
            surface=_SURFACE,
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
    runtime = ClockRuntime(
        gps,
        display,
        rtc,
        emitter=emit,
        clock=time,
        rng=random,
    )
    status.streaming()
    while True:
        try:
            runtime.tick()
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

    hardware = ClockHardware(BOARD, MAX7219, GPS, RTC)
    button.on_press(hardware.flip_display)
    while True:
        status.i2c_init()
        try:
            devices = hardware.open()
        except Exception:  # noqa: BLE001
            status.init_err()
            emit({"diag": "init_err"})
            time.sleep_ms(_INIT_ERR_PAUSE_MS)
            status.boot()
            continue
        run(devices.gps, devices.display, devices.rtc)


main()
