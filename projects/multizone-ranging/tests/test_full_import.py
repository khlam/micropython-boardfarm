"""Host CPython end-to-end import test for multizone-ranging firmware/main.py.

The AST-load fixture in conftest covers function bodies but skips module-level
imports and the trailing main() call. This test stubs sys.modules for every
external dependency and loads main.py as a real module — exercising each
per-chip BOARD branch — while a fake VL53L5CX raises after one frame to escape
stream().
"""

import importlib.util
import io
import json
import os
import pathlib
import sys
from contextlib import redirect_stdout
from types import SimpleNamespace

import pytest

from micropython_stubs.testing import (
    BOARD_CHIPS,
    DeviceNotFoundError,
    FakeStatus,
    build_full_import_stubs,
)

_FIRMWARE = pathlib.Path(__file__).parent.parent / "firmware" / "main.py"
_TOF_ADDRESS = 0x29


@pytest.mark.parametrize("machine_str,board_name", BOARD_CHIPS)
def test_main_executes_init_then_streams_one_frame(monkeypatch, machine_str, board_name):
    fake_status = FakeStatus()
    monkeypatch.setattr(os, "uname", lambda: SimpleNamespace(machine=machine_str))
    for name, module in _build_stubs(fake_status).items():
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.delitem(sys.modules, "main", raising=False)

    spec = importlib.util.spec_from_file_location("main", _FIRMWARE)
    module = importlib.util.module_from_spec(spec)

    buf = io.StringIO()
    with redirect_stdout(buf), pytest.raises(_StopMainError):
        spec.loader.exec_module(module)

    assert module.BOARD.name == board_name
    lines = [json.loads(ln) for ln in buf.getvalue().splitlines() if ln.strip()]
    diags = [ln.get("diag") for ln in lines if "diag" in ln]
    assert "vl53l5cx_ok" in diags
    assert any("grid" in ln for ln in lines)


class _StopMainError(Exception):
    """Raised by the fake sensor on the second read() to escape stream()."""


class _FakeVL53L5CX:
    """Stub VL53L5CX that opens its own bus; second read() raises to escape stream()."""

    def __init__(self, *, sda, scl) -> None:
        self.addr = _TOF_ADDRESS
        self._calls = 0

    def init(self) -> None:
        return None

    def start(self, _freq) -> None:
        return None

    def check_data_ready(self) -> bool:
        return True

    def read(self) -> list[int]:
        self._calls += 1
        if self._calls > 1:
            raise _StopMainError
        return [100] * 64


def _build_stubs(status_stub):
    """Build SimpleNamespace stubs matching main.py's module-level imports."""
    # main() builds VL53L5CX(sda=, scl=) directly — the driver owns the bus and
    # scan — so the project no longer imports i2c_bus; the vl53l5cx stub exposes
    # the driver class and its DeviceNotFoundError.
    vl53l5cx_stub = SimpleNamespace(VL53L5CX=_FakeVL53L5CX, DeviceNotFoundError=DeviceNotFoundError)
    return build_full_import_stubs("vl53l5cx", vl53l5cx_stub, status_stub)
