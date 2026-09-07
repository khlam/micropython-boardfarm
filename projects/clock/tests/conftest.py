"""Host CPython pytest bootstrap for the clock project firmware.

``main.py`` is executed as a real module minus its final ``main()`` call, so the
async runtime (``run_async``, ``clock_program``, ``guarded_program``) and the
board table are all reachable. The firmware reads GPS NMEA sentences, sets an
RTC, and renders the selected clock face on the MAX7219 matrix; the tests drive
the coroutines themselves against fake hardware and a scripted clock.
"""

from __future__ import annotations

import pathlib
import sys
from collections import namedtuple

import machine
import neopixel
import pytest
import utime

from micropython_stubs import asyncio_extras
from micropython_stubs.testing import FakeStatus, load_firmware_module

_FIRMWARE = pathlib.Path(__file__).parent.parent / "firmware" / "main.py"
_MODULE_NAME = "clock_main"

UartWiring = namedtuple("UartWiring", ("bus_id", "tx", "rx"))
PixelSurface = namedtuple("PixelSurface", ("width_pixels", "height_pixels", "brightness"))
DisplayWiring = namedtuple("DisplayWiring", ("spi_id", "sck", "mosi", "cs", "surface"))
Board = namedtuple("Board", ("name", "uart", "display"))

TEST_BOARD = Board(
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


@pytest.fixture(autouse=True)
def _reset_devices() -> None:
    """Clear machine and neopixel state between tests."""
    machine.reset()
    neopixel.reset()


@pytest.fixture(autouse=True)
def _micropython_asyncio(monkeypatch: pytest.MonkeyPatch) -> None:
    """Install MicroPython's asyncio extras (``sleep_ms``) onto the stdlib module."""
    asyncio_extras.install(monkeypatch)


@pytest.fixture
def status(monkeypatch: pytest.MonkeyPatch) -> FakeStatus:
    """Replace the boot LED in every firmware module that drives it.

    ``main`` and ``clock_runtime`` each bind ``boot_status_led.status`` at
    import, so both bindings are swapped for one recorder.

    Args:
        monkeypatch: Fixture used to swap the module-level status bindings.

    Returns:
        The FakeStatus whose ``calls`` list records each LED transition by name.
    """
    import clock_runtime

    recorder = FakeStatus()
    monkeypatch.setattr(clock_runtime, "status", recorder)
    return recorder


@pytest.fixture
def main_module(monkeypatch: pytest.MonkeyPatch, status: FakeStatus) -> object:
    """Execute firmware/main.py as a module with the test board wired in.

    MicroPython's ``time`` carries ``sleep_ms``/``ticks_ms``/``ticks_diff``, which
    host CPython's does not, so the ``utime`` stub stands in for it while the
    firmware executes — and its ``sleep_ms`` returns immediately, so boot pauses
    cost nothing. The BOOT-button registration is neutralised so importing the
    firmware does not claim a pin, and ``BOARD`` is pinned to a known wiring
    table so the pin assertions do not depend on which chip the host reports.

    Args:
        monkeypatch: Fixture used to install the stubs and pin the board table.
        status: LED recorder bound into the executed module.

    Returns:
        The executed ``main.py`` module, minus its final ``main()`` call.
    """
    monkeypatch.setitem(sys.modules, "time", utime)
    module = load_firmware_module(_FIRMWARE, _MODULE_NAME, "main")
    monkeypatch.setattr(module, "BOARD", TEST_BOARD)
    monkeypatch.setattr(module, "status", status)
    monkeypatch.setattr(module.button, "on_press", lambda _cb: None)
    return module
