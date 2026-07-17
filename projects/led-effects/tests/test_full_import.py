"""Host CPython end-to-end import test for led-effects firmware/main.py.

Mirrors gyro-stream's full-import: stubs sys.modules and loads main.py as a
real module so the imports and trailing main() call run. A fake Strip raises
after a few renders to escape run()'s endless effect cycle.
"""

import importlib.util
import io
import json
import os
import pathlib
import sys
from contextlib import redirect_stdout
from types import SimpleNamespace
from typing import ClassVar

import pytest

from micropython_stubs.testing import BOARD_CHIPS, FakeStatus, build_full_import_stubs
from ws2812b import Breathe, ColorFade, HueRotate, Rainbow

_FIRMWARE = pathlib.Path(__file__).parent.parent / "firmware" / "main.py"
# Expected strip data pin per BOARD.name — ESP32-S3-Zero wires DIN to GPIO7,
# the RP boards to GP15.
_DATA_PIN = {"RP2040-Zero": 15, "RP2350": 15, "ESP32-S3-Zero": 7}
_RENDERS_BEFORE_STOP = 3


@pytest.mark.parametrize("machine_str,board_name", BOARD_CHIPS)
def test_main_builds_strip_on_board_pin_and_starts_cycle(monkeypatch, machine_str, board_name):
    fake_status = FakeStatus()
    monkeypatch.setattr(os, "uname", lambda: SimpleNamespace(machine=machine_str))
    for name, module in _build_stubs(fake_status).items():
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.delitem(sys.modules, "main", raising=False)
    _FakeStrip.instances.clear()

    spec = importlib.util.spec_from_file_location("main", _FIRMWARE)
    module = importlib.util.module_from_spec(spec)

    buf = io.StringIO()
    with redirect_stdout(buf), pytest.raises(_StopMainError):
        spec.loader.exec_module(module)

    assert module.BOARD.name == board_name
    strip = _FakeStrip.instances[-1]
    assert strip.pin == _DATA_PIN[board_name]
    assert strip.count == module.LED_COUNT
    assert all(len(frame) == module.LED_COUNT for frame in strip.frames)
    lines = [json.loads(ln) for ln in buf.getvalue().splitlines() if ln.strip()]
    assert lines == [{"effect": "rainbow"}]
    assert fake_status.calls == ["boot", "streaming"]


class _StopMainError(Exception):
    """Raised by the fake Strip after a few renders to escape run()."""


class _FakeStrip:
    """Records construction pin/count and rendered frames; raises to escape run()."""

    instances: ClassVar[list["_FakeStrip"]] = []

    def __init__(self, count, *, pin) -> None:
        self.count = count
        self.pin = pin
        self.frames = []
        _FakeStrip.instances.append(self)

    def render(self, frame):
        self.frames.append(list(frame))
        if len(self.frames) >= _RENDERS_BEFORE_STOP:
            raise _StopMainError


def _build_stubs(status_stub):
    # main.py imports the Strip driver and the four effect classes from
    # ws2812b; the effects are pure math, so the stub re-exports the real
    # ones and only fakes the hardware-facing Strip.
    ws2812b_stub = SimpleNamespace(
        Strip=_FakeStrip,
        Breathe=Breathe,
        ColorFade=ColorFade,
        HueRotate=HueRotate,
        Rainbow=Rainbow,
    )
    return build_full_import_stubs("ws2812b", ws2812b_stub, status_stub)
