"""Host CPython end-to-end import test for distance-stream firmware/main.py.

The AST-load fixture in conftest covers function bodies but skips
module-level imports and the trailing main() call. This test stubs
sys.modules for every external dependency and loads main.py as a real
module; a fake VL53L0X raises after one sample to escape stream().
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
TOF_ADDRESS = 0x29


@pytest.mark.parametrize("machine_str,board_name", BOARD_CHIPS)
def test_main_executes_init_then_streams_one_sample(monkeypatch, machine_str, board_name):
    fake_status = FakeStatus()
    monkeypatch.setattr(os, "uname", lambda: SimpleNamespace(machine=machine_str))
    for name, module in _build_stubs(fake_status).items():
        monkeypatch.setitem(sys.modules, name, module)
    # Earlier tests load main.py via AST-exec, leaving an entry in sys.modules.
    monkeypatch.delitem(sys.modules, "main", raising=False)

    spec = importlib.util.spec_from_file_location("main", _FIRMWARE)
    module = importlib.util.module_from_spec(spec)

    buf = io.StringIO()
    with redirect_stdout(buf), pytest.raises(_StopMainError):
        spec.loader.exec_module(module)

    assert module.BOARD.name == board_name
    lines = [json.loads(ln) for ln in buf.getvalue().splitlines() if ln.strip()]
    diags = [ln.get("diag") for ln in lines if "diag" in ln]
    assert "tof_ok" in diags
    assert any("distance_mm" in ln for ln in lines)


class _StopMainError(Exception):
    """Raised by the fake tof on the second read() to escape stream()."""


class _FakeVL53L0X:
    """Stub VL53L0X that opens its own bus; second read() raises to escape stream()."""

    def __init__(self, *, sda, scl) -> None:
        self.address = TOF_ADDRESS
        self._calls = 0

    def set_measurement_timing_budget(self, _budget):
        return None

    def start(self):
        return None

    def read(self):
        self._calls += 1
        if self._calls > 1:
            raise _StopMainError
        return 500


def _build_stubs(status_stub):
    """Build SimpleNamespace stubs matching main.py's module-level imports."""
    # main() now builds VL53L0X(sda=, scl=) directly — the driver owns the bus,
    # scan, and soft reset — so the project no longer imports i2c_bus; the
    # vl53l0x stub exposes the driver class and its DeviceNotFoundError.
    vl53l0x_stub = SimpleNamespace(VL53L0X=_FakeVL53L0X, DeviceNotFoundError=DeviceNotFoundError)
    return build_full_import_stubs("vl53l0x", vl53l0x_stub, status_stub)
