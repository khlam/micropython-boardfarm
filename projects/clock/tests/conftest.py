"""Host CPython pytest bootstrap for the clock project firmware.

Uses the shared ``firmware_namespace`` helper to AST-load main.py with hardware
fakes injected. The firmware reads GPS NMEA sentences, sets an RTC, and renders
the selected clock face on the MAX7219 matrix.
"""

from __future__ import annotations

import os
import pathlib
import random
import sys
from collections import namedtuple
from types import SimpleNamespace

import machine
import neopixel
import pytest

from micropython_stubs.testing import firmware_namespace

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

_TEST_BOARD = Board(
    name="RP2040-Zero",
    uart=UartWiring(bus_id=0, tx=0, rx=1),
    display=DisplayWiring(
        spi_id=1,
        sck=26,
        mosi=27,
        cs=28,
        surface=PixelSurface(width_pixels=32, height_pixels=16, brightness=0.2),
    ),
)

_HERE = pathlib.Path(__file__).parent.resolve()
_FIRMWARE_DIR = _HERE.parent / "firmware"
_FIRMWARE = _FIRMWARE_DIR / "main.py"
if str(_FIRMWARE_DIR) not in sys.path:
    sys.path.insert(0, str(_FIRMWARE_DIR))

_KEEP_FUNCS = {
    "run",
    "main",
}


@pytest.fixture(autouse=True)
def _reset_devices() -> None:
    """Clear machine and neopixel state between tests."""
    machine.reset()
    neopixel.reset()


@pytest.fixture
def main_ns() -> SimpleNamespace:
    """Fresh AST-loaded main.py namespace with fakes injected.

    Returns:
        SimpleNamespace with ``ns``, ``time``, and ``status`` attributes.
    """
    import clock_cycle
    import clock_sync

    return firmware_namespace(
        _FIRMWARE,
        _KEEP_FUNCS,
        os=os,
        namedtuple=namedtuple,
        BOARD=_TEST_BOARD,
        random=random,
        button=SimpleNamespace(on_press=lambda _cb: None),
        DisplayCycle=clock_cycle.DisplayCycle,
        POLL_SLEEP_MS=clock_cycle.POLL_SLEEP_MS,
        emit=clock_sync.emit,
        sync_from_line=clock_sync.sync_from_line,
    )
