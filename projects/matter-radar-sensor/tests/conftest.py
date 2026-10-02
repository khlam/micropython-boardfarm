"""Shared deterministic runtime for the matter-radar-sensor firmware tests."""

import gc
import importlib
import os
import pathlib
import sys
from collections.abc import Callable, Iterator
from types import ModuleType, SimpleNamespace

import machine
import matter_native
import neopixel
import pytest
from microdot import microdot

import matter.emit as matter_emit
import matter.node as matter_node
from micropython_stubs import asyncio_extras
from micropython_stubs.testing import load_firmware_module

_FIRMWARE = pathlib.Path(__file__).parent.parent / "firmware" / "main.py"
_MODULE_NAME = "matter_radar_sensor_main"
# The one fabric a commissioned boot restores: index, fabric, node, vendor, label.
_FABRIC = (1, 0x1234, 0x5678, 0xFFF1, "controller")


class FakeTime:
    """Wrap-safe monotonic time controlled directly by each test."""

    _PERIOD = 1 << 30
    _HALF_PERIOD = 1 << 29

    def __init__(self) -> None:
        """Start at tick zero with no scripted readings."""
        self.ticks = 0
        self.script = []

    def ticks_ms(self) -> int:
        """Return the next scripted tick or the current tick.

        Returns:
            The tick in milliseconds.
        """
        if self.script:
            self.ticks = self.script.pop(0)
        return self.ticks

    def ticks_diff(self, newer: int, older: int) -> int:
        """Return MicroPython's signed wrap-safe tick difference.

        Args:
            newer: The later tick.
            older: The earlier tick.

        Returns:
            ``newer - older`` in milliseconds, correct across one wrap.
        """
        return (newer - older + self._HALF_PERIOD) % self._PERIOD - self._HALF_PERIOD

    def ticks_add(self, ticks: int, delta: int) -> int:
        """Add milliseconds with the device's tick wrap.

        Args:
            ticks: The starting tick.
            delta: Milliseconds to add; may be negative.

        Returns:
            The wrapped sum.
        """
        return (ticks + delta) % self._PERIOD


@pytest.fixture(autouse=True)
def reset_runtime(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Reset process-wide MCU and Matter fakes around every test.

    Args:
        monkeypatch: Installs MicroPython asyncio names and restores the microdot hook.

    Yields:
        None: Control to the test between the two resets.
    """
    asyncio_extras.install(monkeypatch)
    monkeypatch.setattr(microdot, "print_exception", microdot.print_exception)
    _reset_state()
    yield
    _reset_state()


@pytest.fixture
def firmware_module(monkeypatch: pytest.MonkeyPatch) -> Callable[[str], ModuleType]:
    """Return an importer for one firmware module running on the wrap-safe fake clock.

    Args:
        monkeypatch: Puts the firmware directory on the path and swaps in the clock.

    Returns:
        The importer.
    """
    clock = FakeTime()

    def load(name: str) -> ModuleType:
        _install_firmware_path(monkeypatch)
        module = importlib.import_module(name)
        if hasattr(module, "time"):
            monkeypatch.setattr(module, "time", clock)
        return module

    return load


@pytest.fixture
def load_firmware(monkeypatch: pytest.MonkeyPatch) -> Callable[..., SimpleNamespace]:
    """Return a loader for the complete firmware module without its infinite entry call.

    Args:
        monkeypatch: Fakes the board name, clock, free memory, and import path.

    Returns:
        The loader, returning the module and its fake clock.
    """

    def load(
        *,
        machine_name: str = "Generic ESP32S3 module with ESP32S3",
        commissioned: bool = False,
    ) -> SimpleNamespace:
        _reset_state(commissioned=commissioned)

        clock = FakeTime()
        _install_firmware_path(monkeypatch)
        monkeypatch.setattr(os, "uname", lambda: SimpleNamespace(machine=machine_name))
        monkeypatch.setitem(sys.modules, "time", clock)
        monkeypatch.setattr(gc, "mem_free", lambda: 128 * 1024, raising=False)

        module = load_firmware_module(_FIRMWARE, _MODULE_NAME, "main")
        return SimpleNamespace(module=module, time=clock)

    return load


@pytest.fixture
def load_application(
    load_firmware: Callable[..., SimpleNamespace],
) -> Callable[..., SimpleNamespace]:
    """Return a loader that also constructs the firmware application.

    Args:
        load_firmware: Loads the firmware module the application comes from.

    Returns:
        The loader, returning the application, its modules, and the fake clock.
    """

    def load(**kwargs) -> SimpleNamespace:
        firmware = load_firmware(**kwargs)
        application = firmware.module._Application()
        return SimpleNamespace(
            module=firmware.module,
            application=application,
            time=firmware.time,
            webserver_module=sys.modules["webserver"],
            status_module=sys.modules["status"],
        )

    return load


def _reset_state(*, commissioned: bool = False) -> None:
    """Reset every process-wide fake used by the firmware module.

    Args:
        commissioned: Seed flash with one fabric, as a paired device boots.
    """
    machine.reset()
    neopixel.reset()
    matter_native.reset()
    matter_native.seed_fabrics([_FABRIC] if commissioned else [])
    matter_node._active_node[0] = None
    matter_emit._sinks.clear()
    for name in (_MODULE_NAME, "webserver", "status", "reports"):
        sys.modules.pop(name, None)


def _install_firmware_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the firmware directory and its generated dashboard page importable.

    Args:
        monkeypatch: Undoes the path and module entries after the test.
    """
    monkeypatch.syspath_prepend(str(_FIRMWARE.parent))
    monkeypatch.setitem(
        sys.modules,
        "dashboard_page",
        SimpleNamespace(PAGE=b"dashboard", ENCODING="gzip"),
    )
