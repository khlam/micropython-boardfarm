"""Host CPython pytest bootstrap for the clock project firmware.

Uses the shared ``firmware_namespace`` helper to AST-load main.py with fakes
for ``time`` and ``status`` injected. The current main.py is a display
bring-up: it opens a MAX7219, shows two words, and idles with periodic
``reassert``.
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

Board = namedtuple("Board", ("name", "spi_id", "sck", "mosi", "cs"))

_TEST_BOARD = Board(name="RP2040-Zero", spi_id=1, sck=26, mosi=27, cs=28)

_HERE = pathlib.Path(__file__).parent.resolve()
_FIRMWARE = _HERE.parent / "firmware" / "main.py"

_KEEP_FUNCS = {
    "emit",
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

    Returns a SimpleNamespace with:
        - .ns: dict of module-level names (emit, run, main)
        - .time: the FakeTime instance used as the ``time`` module
        - .status: the FakeStatus instance; inspect .calls for transitions
    """
    return firmware_namespace(
        _FIRMWARE,
        _KEEP_FUNCS,
        os=os,
        namedtuple=namedtuple,
        BOARD=_TEST_BOARD,
    )
