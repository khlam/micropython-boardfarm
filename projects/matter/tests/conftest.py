"""Shared fixtures for the Matter example firmware tests."""

import io
import os
import pathlib
import sys
from collections.abc import Callable, Iterable, Iterator
from contextlib import redirect_stdout
from types import ModuleType, SimpleNamespace

import machine
import matter_native
import neopixel
import pytest

import matter.node as matter_node
from micropython_stubs.testing import FakeTime, json_lines, load_firmware_module

_FIRMWARE = pathlib.Path(__file__).parent.parent / "firmware"
_MAIN = _FIRMWARE / "main.py"
_MAIN_MODULE = "matter_project_main"


def _reset_state(
    *, persisted: dict[tuple[int, int, int], object] | None = None, fabrics: Iterable[tuple] = ()
) -> None:
    """Reset every process-wide fake used by the firmware import.

    Args:
        persisted: Attribute values flash holds, keyed by (endpoint, cluster,
            attribute); None for empty flash.
        fabrics: The fabrics the node is commissioned into.
    """
    machine.reset()
    neopixel.reset()
    matter_native.reset(persisted=persisted)
    matter_native.seed_fabrics(list(fabrics))
    matter_node._active_node[0] = None
    for name in (_MAIN_MODULE, "color", "color.convert"):
        sys.modules.pop(name, None)


@pytest.fixture(autouse=True)
def reset_runtime() -> Iterator[None]:
    """Reset process-wide MCU and Matter fakes around every test.

    Yields:
        None: Control to the test between the two resets.
    """
    _reset_state()
    yield
    _reset_state()


@pytest.fixture
def color_module(monkeypatch: pytest.MonkeyPatch) -> Iterator[ModuleType]:
    """Import a fresh copy of the project's public color module.

    Args:
        monkeypatch: Puts the firmware directory on the import path.

    Yields:
        ModuleType: The color module, dropped from the import cache afterwards.
    """
    monkeypatch.syspath_prepend(str(_FIRMWARE))
    module = __import__("color")
    yield module
    sys.modules.pop("color.convert", None)
    sys.modules.pop("color", None)


@pytest.fixture
def load_main(monkeypatch: pytest.MonkeyPatch) -> Callable[..., SimpleNamespace]:
    """Return a factory that executes the real firmware module once.

    Args:
        monkeypatch: Fakes the board name, clock, import path, and native start.

    Returns:
        The factory, returning the module, its fake clock, and its startup lines.
    """

    def load(
        *,
        machine_name="Generic ESP32S3 module with ESP32S3",
        persisted=None,
        fabrics=(),
        commissioning=(),
    ):
        _reset_state(persisted=persisted, fabrics=fabrics)

        fake_time = FakeTime()
        monkeypatch.setattr(os, "uname", lambda: SimpleNamespace(machine=machine_name))
        monkeypatch.setitem(sys.modules, "time", fake_time)
        monkeypatch.syspath_prepend(str(_FIRMWARE))

        if commissioning:
            native_start = matter_native.start

            def start_with_events():
                native_start()
                for state_code in commissioning:
                    matter_native.inject_commissioning_event(state_code)

            monkeypatch.setattr(matter_native, "start", start_with_events)

        output = io.StringIO()
        with redirect_stdout(output):
            module = load_firmware_module(_MAIN, _MAIN_MODULE, "run")
        return SimpleNamespace(module=module, time=fake_time, lines=json_lines(output.getvalue()))

    return load
