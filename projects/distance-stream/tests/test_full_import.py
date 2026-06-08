"""Host CPython end-to-end import test for distance-stream firmware/main.py.

The AST-load fixture in conftest covers function bodies but skips
module-level imports and the trailing main() call. This test stubs
sys.modules for every external dependency and loads main.py as a real
module; a fake VL53L0X raises after one sample to escape stream().
"""

import importlib.util
import io
import json
import pathlib
import sys
from contextlib import redirect_stdout
from types import SimpleNamespace

import pytest

_FIRMWARE = pathlib.Path(__file__).parent.parent / "firmware" / "main.py"
TOF_ADDRESS = 0x29


def test_main_executes_init_then_streams_one_sample(monkeypatch, fake_status):
    for name, module in _build_stubs(fake_status).items():
        monkeypatch.setitem(sys.modules, name, module)
    # Earlier tests load main.py via AST-exec, leaving an entry in sys.modules.
    monkeypatch.delitem(sys.modules, "main", raising=False)

    spec = importlib.util.spec_from_file_location("main", _FIRMWARE)
    module = importlib.util.module_from_spec(spec)

    buf = io.StringIO()
    with redirect_stdout(buf), pytest.raises(_StopMainError):
        spec.loader.exec_module(module)

    lines = [json.loads(ln) for ln in buf.getvalue().splitlines() if ln.strip()]
    diags = [ln.get("diag") for ln in lines if "diag" in ln]
    assert "scan" in diags
    assert "tof_ok" in diags
    assert any("distance_mm" in ln for ln in lines)


class _StopMainError(Exception):
    """Raised by the fake tof on the second read() to escape stream()."""


class _Bus:
    """Minimal I²C bus stub: scans to TOF_ADDRESS, returns a booted MODEL_ID."""

    @staticmethod
    def scan() -> list[int]:
        return [TOF_ADDRESS]

    @staticmethod
    def writeto_mem(_addr, _reg, _buf) -> None:
        return None

    @staticmethod
    def readfrom_mem(_addr, _reg, _n) -> bytes:
        return b"\xee"  # _MODEL_ID_BOOTED


class _FakeVL53L0X:
    """Stub VL53L0X driver; second read() raises to escape stream()."""

    def __init__(self, _bus, *, skip_spad_info=False, interrupt_status_mask=0) -> None:
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
    time_stub = SimpleNamespace(
        sleep_ms=lambda _ms: None,
        ticks_ms=lambda: 0,
    )
    boot_status_led_stub = SimpleNamespace(status=status_stub)
    i2c_bus_stub = SimpleNamespace(soft_i2c=_Bus())
    vl53l0x_stub = SimpleNamespace(VL53L0X=_FakeVL53L0X)

    return {
        "time": time_stub,
        "ujson": __import__("json"),
        "boot_status_led": boot_status_led_stub,
        "boot_status_led.status": status_stub,
        "i2c_bus": i2c_bus_stub,
        "vl53l0x": vl53l0x_stub,
    }
