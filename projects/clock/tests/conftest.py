"""Host CPython pytest bootstrap for the clock project firmware.

``main.py`` is executed as a real module minus its final ``main()`` call, so the
async runtime (``run_async``, ``clock_program``, ``guarded_program``) and the
board table are all reachable. The firmware reads GPS NMEA sentences, sets an
RTC, and renders the selected clock face on the MAX7219 matrix; the tests drive
the coroutines themselves against fake hardware and a scripted clock.
"""

from __future__ import annotations

import os
import pathlib
import sys
from types import SimpleNamespace

import machine
import neopixel
import pytest
import utime

from micropython_stubs import asyncio_extras
from micropython_stubs.testing import FakeStatus, load_firmware_module

_FIRMWARE = pathlib.Path(__file__).parent.parent / "firmware" / "main.py"
_MODULE_NAME = "clock_main"


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
def status() -> FakeStatus:
    """Return the recorder that stands in for the boot LED.

    ``main_module`` binds it over the module's own ``boot_status_led.status``
    once the firmware has been executed.

    Returns:
        The FakeStatus whose ``calls`` list records each LED transition by name.
    """
    return FakeStatus()


@pytest.fixture
def main_module(
    monkeypatch: pytest.MonkeyPatch, status: FakeStatus, request: pytest.FixtureRequest
) -> object:
    """Execute firmware/main.py as a module with the test board wired in.

    MicroPython's ``time`` carries ``sleep_ms``/``ticks_ms``/``ticks_diff``, which
    host CPython's does not, so the ``utime`` stub stands in for it while the
    firmware executes — and its ``sleep_ms`` returns immediately, so boot pauses
    cost nothing. The BOOT-button registration is neutralised so importing the
    firmware does not claim a pin. The machine identity selects the real board
    table, defaulting to RP2040 unless the test parametrizes another chip.

    Args:
        monkeypatch: Fixture used to install the stubs and pin the board table.
        status: LED recorder bound into the executed module.
        request: Optional indirect machine-identity parameter.

    Returns:
        The executed ``main.py`` module, minus its final ``main()`` call.
    """
    monkeypatch.setitem(sys.modules, "time", utime)
    machine_name = getattr(request, "param", "RP2040 with RP2040")
    monkeypatch.setattr(os, "uname", lambda: SimpleNamespace(machine=machine_name))
    module = load_firmware_module(_FIRMWARE, _MODULE_NAME, "main")
    monkeypatch.setattr(module, "status", status)
    monkeypatch.setattr(module.button, "on_press", lambda _cb: None)
    return module
