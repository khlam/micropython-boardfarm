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

from micropython_stubs.testing import FakeStatus, FakeTime, firmware_namespace
from nmea import apply_parsed, nmea_checksum_valid, parse_sentence
from tz_offset import local_from_gps, offset_hours_from_longitude

UartWiring = namedtuple("UartWiring", ("bus_id", "tx", "rx"))
DisplayWiring = namedtuple("DisplayWiring", ("spi_id", "sck", "mosi", "cs"))
Board = namedtuple("Board", ("name", "uart", "display"))

_TEST_BOARD = Board(
    name="RP2040-Zero",
    uart=UartWiring(bus_id=0, tx=0, rx=1),
    display=DisplayWiring(spi_id=1, sck=26, mosi=27, cs=28),
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
def fake_time() -> FakeTime:
    """Provide a fresh FakeTime instance."""
    return FakeTime()


@pytest.fixture
def fake_status() -> FakeStatus:
    """Provide a fresh FakeStatus instance."""
    return FakeStatus()


@pytest.fixture
def main_ns(fake_time: FakeTime, fake_status: FakeStatus) -> SimpleNamespace:
    """Fresh AST-loaded main.py namespace with fakes injected.

    Args:
        fake_time: Fake time module injected into the firmware namespace.
        fake_status: Fake status LED module injected into the firmware namespace.

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
        local_from_gps=local_from_gps,
        offset_hours_from_longitude=offset_hours_from_longitude,
    )
