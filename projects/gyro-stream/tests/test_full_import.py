"""Host CPython end-to-end import test for gyro-stream firmware/main.py.

Mirrors distance-stream's full-import: stubs sys.modules and loads
main.py as a real module so the imports and trailing main() call run.
A fake MPU6050 raises after one sample to escape stream().
"""

import importlib.util
import io
import json
import pathlib
import sys
from collections.abc import Callable
from contextlib import redirect_stdout
from types import SimpleNamespace

import pytest

_FIRMWARE = pathlib.Path(__file__).parent.parent / "firmware" / "main.py"
PRIMARY = 0x68


def test_main_executes_init_then_streams_one_sample(monkeypatch):
    for name, module in _build_stubs().items():
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.delitem(sys.modules, "main", raising=False)

    spec = importlib.util.spec_from_file_location("main", _FIRMWARE)
    module = importlib.util.module_from_spec(spec)

    buf = io.StringIO()
    with redirect_stdout(buf), pytest.raises(_StopMainError):
        spec.loader.exec_module(module)

    lines = [json.loads(ln) for ln in buf.getvalue().splitlines() if ln.strip()]
    diags = [ln.get("diag") for ln in lines if "diag" in ln]
    assert "scan" in diags
    assert "imu_ok" in diags
    assert any("ax" in ln for ln in lines)


class _StopMainError(Exception):
    """Raised by the fake IMU on the second read_all() to escape stream()."""


class _Status:
    """Records named status transitions invoked by main.py."""

    def __init__(self) -> None:
        self.calls = []

    def __getattr__(self, name) -> Callable[[], None]:
        if name.startswith("_"):
            raise AttributeError(name)

        def _rec() -> None:
            self.calls.append(name)

        return _rec


class _Bus:
    """Minimal I²C bus stub: scans to the MPU6050 primary address."""

    @staticmethod
    def scan() -> list[int]:
        return [PRIMARY]


class _FakeIMU:
    """Stub MPU6050; second read_all() raises to escape stream()."""

    def __init__(self, _bus, *, addr) -> None:
        self.addr = addr
        self.kind = "MPU6050"
        self.last_saturated = False
        self._calls = 0

    def read_all(self):
        self._calls += 1
        if self._calls > 1:
            raise _StopMainError
        return (0.01, -0.02, 0.99, 0.1, -0.05, 0.0, 24.7)


def _build_stubs():
    time_stub = SimpleNamespace(
        sleep_ms=lambda _ms: None,
        ticks_ms=lambda: 0,
    )
    status_stub = _Status()
    boot_status_led_stub = SimpleNamespace(status=status_stub)
    i2c_bus_stub = SimpleNamespace(hard_i2c=_Bus())
    mpu6050_stub = SimpleNamespace(MPU6050=_FakeIMU)

    return {
        "time": time_stub,
        "ujson": __import__("json"),
        "boot_status_led": boot_status_led_stub,
        "boot_status_led.status": status_stub,
        "i2c_bus": i2c_bus_stub,
        "mpu6050": mpu6050_stub,
    }
