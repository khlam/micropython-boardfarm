"""Host CPython pytest bootstrap for the clock project firmware.

Uses the shared ``firmware_namespace`` helper to AST-load main.py with hardware
fakes injected. The firmware reads GPS NMEA sentences, sets an RTC, and renders
the current local time/date on the MAX7219 matrix.
"""

from __future__ import annotations

import os
import pathlib
from collections import namedtuple
from types import SimpleNamespace

import machine
import neopixel
import pytest

from micropython_stubs.testing import firmware_namespace
from nmea import apply_parsed, nmea_checksum_valid, parse_sentence
from pixel_display import Frame
from tz_offset import local_from_gps, offset_hours_from_longitude

UartWiring = namedtuple("UartWiring", ("bus_id", "tx", "rx"))
DisplayWiring = namedtuple(
    "DisplayWiring",
    (
        "spi_id",
        "sck",
        "mosi",
        "cs",
        "width_pixels",
        "height_pixels",
        "intensity_min",
        "intensity_max",
        "intensity_limit",
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
        width_pixels=32,
        height_pixels=16,
        intensity_min=0,
        intensity_max=15,
        intensity_limit=0.2,
    ),
)

_HERE = pathlib.Path(__file__).parent.resolve()
_FIRMWARE = _HERE.parent / "firmware" / "main.py"

_KEEP_FUNCS = {
    "emit",
    "_iso_local",
    "_rtc_datetime",
    "_display_lines",
    "_show",
    "_refresh_display",
    "_sync_from_line",
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
    return firmware_namespace(
        _FIRMWARE,
        _KEEP_FUNCS,
        os=os,
        namedtuple=namedtuple,
        BOARD=_TEST_BOARD,
        apply_parsed=apply_parsed,
        nmea_checksum_valid=nmea_checksum_valid,
        parse_sentence=parse_sentence,
        Frame=Frame,
        local_from_gps=local_from_gps,
        offset_hours_from_longitude=offset_hours_from_longitude,
    )
