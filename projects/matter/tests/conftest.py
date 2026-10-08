"""Shared fixtures for the Matter example firmware tests."""

import io
import os
import pathlib
import sys
from contextlib import redirect_stdout
from types import SimpleNamespace

import machine
import matter_native
import neopixel
import pytest

import matter.node as matter_node
from micropython_stubs.testing import FakeTime, json_lines, load_firmware_module

_FIRMWARE = pathlib.Path(__file__).parent.parent / "firmware"
_MAIN = _FIRMWARE / "main.py"
_MAIN_MODULE = "matter_project_main"


def _reset_state(*, persisted=None, fabrics=()) -> None:
    """Reset every process-wide fake used by the firmware import."""
    machine.reset()
    neopixel.reset()
    matter_native.reset(persisted=persisted)
    matter_native.seed_fabrics(list(fabrics))
    matter_node._active_node[0] = None
    for name in (_MAIN_MODULE, "color", "color.convert"):
        sys.modules.pop(name, None)


@pytest.fixture(autouse=True)
def reset_runtime():
    """Reset process-wide MCU and Matter fakes around every test."""
    _reset_state()
    yield
    _reset_state()


@pytest.fixture
def color_module(monkeypatch):
    """Import a fresh copy of the project's public color module."""
    monkeypatch.syspath_prepend(str(_FIRMWARE))
    module = __import__("color")
    yield module
    sys.modules.pop("color.convert", None)
    sys.modules.pop("color", None)


@pytest.fixture
def load_main(monkeypatch):
    """Return a factory that executes the real firmware module once."""

    def load(
        *,
        machine_name="Generic ESP32S3 module with ESP32S3",
        persisted=None,
        fabrics=(),
    ):
        _reset_state(persisted=persisted, fabrics=fabrics)

        fake_time = FakeTime()
        monkeypatch.setattr(os, "uname", lambda: SimpleNamespace(machine=machine_name))
        monkeypatch.setitem(sys.modules, "time", fake_time)
        monkeypatch.syspath_prepend(str(_FIRMWARE))

        output = io.StringIO()
        with redirect_stdout(output):
            module = load_firmware_module(_MAIN, _MAIN_MODULE, "run")
        return SimpleNamespace(module=module, time=fake_time, lines=json_lines(output.getvalue()))

    return load
