"""Host CPython end-to-end import test for gyro-stream firmware/main.py.

Mirrors distance-stream's full-import: stubs sys.modules and loads
main.py as a real module so the imports and trailing main() call run.
A fake MPU6050 raises after one sample to escape stream().
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
PRIMARY = 0x68


@pytest.mark.parametrize("machine_str,board_name", BOARD_CHIPS)
def test_main_executes_init_then_streams_one_sample(monkeypatch, machine_str, board_name):
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
    assert "imu_ok" in diags
    assert any("ax" in ln for ln in lines)


class _StopMainError(Exception):
    """Raised by the fake IMU on the second read_all() to escape stream()."""


class _FakeIMU:
    """Stub MPU6050 that opens its own bus; second read_all() raises to escape stream()."""

    def __init__(self, *, sda, scl, bus_id=0) -> None:
        self.addr = PRIMARY
        self.kind = "MPU6050"
        self.last_saturated = False
        self._calls = 0

    def read_all(self):
        self._calls += 1
        if self._calls > 1:
            raise _StopMainError
        return (0.01, -0.02, 0.99, 0.1, -0.05, 0.0, 24.7)


def _build_stubs(status_stub):
    # main() now builds MPU6050(id=, sda=, scl=) directly — the driver owns the
    # bus and the address probe — so the project no longer imports i2c_bus; the
    # mpu6050 stub exposes the driver class and its DeviceNotFoundError.
    mpu6050_stub = SimpleNamespace(MPU6050=_FakeIMU, DeviceNotFoundError=DeviceNotFoundError)
    return build_full_import_stubs("mpu6050", mpu6050_stub, status_stub)
