"""Host CPython end-to-end import test for compass firmware/main.py.

Mirrors gyro-stream's full-import: stubs sys.modules and loads main.py as a real
module so the imports and trailing main() call run. A fake QMC5883P raises after
one sample to escape stream().
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
ADDR = 0x2C


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
    assert "mag_ok" in diags
    assert any("heading_deg" in ln for ln in lines)


class _StopMainError(Exception):
    """Raised by the fake mag on the second read() to escape stream()."""


class _FakeMag:
    """Stub QMC5883P that opens its own bus; second read() raises to escape stream()."""

    def __init__(self, *, sda, scl, bus_id=0, address=ADDR) -> None:
        self.address = address
        self.last_status = 0
        self._calls = 0

    def read(self):
        self._calls += 1
        if self._calls > 1:
            raise _StopMainError
        return (100, -50, 200)


def _build_stubs(status_stub):
    # main() now builds QMC5883P(id=, sda=, scl=) directly — the driver owns the
    # bus — so the project no longer imports i2c_bus; the qmc5883p stub exposes
    # the driver class and its DeviceNotFoundError.
    qmc5883p_stub = SimpleNamespace(QMC5883P=_FakeMag, DeviceNotFoundError=DeviceNotFoundError)
    return build_full_import_stubs("qmc5883p", qmc5883p_stub, status_stub)
