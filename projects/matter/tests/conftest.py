"""Shared fixtures for the Matter example firmware tests."""

import importlib.util
import io
import json
import os
import pathlib
import sys
from contextlib import redirect_stdout
from types import SimpleNamespace

import _matter
import machine
import neopixel
import pytest

import matter.node as matter_node
from micropython_stubs.testing import FakeTime

_FIRMWARE = pathlib.Path(__file__).parent.parent / "firmware"
_MAIN = _FIRMWARE / "main.py"
_MAIN_MODULE = "matter_project_main"


@pytest.fixture(autouse=True)
def reset_runtime():
    """Reset every process-wide fake used by the firmware import."""
    machine.reset()
    neopixel.reset()
    _matter.reset()
    matter_node._active_node[0] = None
    for name in (_MAIN_MODULE, "color", "color.convert"):
        sys.modules.pop(name, None)
    yield
    machine.reset()
    neopixel.reset()
    _matter.reset()
    matter_node._active_node[0] = None
    for name in (_MAIN_MODULE, "color", "color.convert"):
        sys.modules.pop(name, None)


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
        commissioning=(),
    ):
        _matter.reset(persisted=persisted)
        _matter.seed_fabrics(list(fabrics))
        matter_node._active_node[0] = None
        machine.reset()
        neopixel.reset()
        for name in (_MAIN_MODULE, "color", "color.convert"):
            sys.modules.pop(name, None)

        fake_time = FakeTime()
        monkeypatch.setattr(os, "uname", lambda: SimpleNamespace(machine=machine_name))
        monkeypatch.setitem(sys.modules, "time", fake_time)
        monkeypatch.syspath_prepend(str(_FIRMWARE))

        if commissioning:
            native_start = _matter.start

            def start_with_events():
                native_start()
                for state_code in commissioning:
                    _matter.inject_commissioning_event(state_code)

            monkeypatch.setattr(_matter, "start", start_with_events)

        spec = importlib.util.spec_from_file_location(_MAIN_MODULE, _MAIN)
        module = importlib.util.module_from_spec(spec)
        sys.modules[_MAIN_MODULE] = module
        output = io.StringIO()
        with redirect_stdout(output):
            spec.loader.exec_module(module)
        lines = [json.loads(line) for line in output.getvalue().splitlines() if line]
        return SimpleNamespace(module=module, time=fake_time, lines=lines)

    return load
