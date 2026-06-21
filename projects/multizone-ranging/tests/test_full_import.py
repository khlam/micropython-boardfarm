"""Host CPython end-to-end import test for multizone-ranging firmware/main.py.

The AST-load fixture in conftest covers function bodies but skips module-level
imports and the trailing main() call. This test stubs sys.modules for every
external dependency and loads main.py as a real module — exercising each
per-chip BOARD branch — while a fake VL53L5CX raises after one frame to escape
stream().
"""

import collections
import importlib.util
import io
import json
import os
import pathlib
import sys
from contextlib import redirect_stdout
from types import SimpleNamespace

import pytest

_FIRMWARE = pathlib.Path(__file__).parent.parent / "firmware" / "main.py"
_TOF_ADDRESS = 0x29

# (os.uname().machine string, expected BOARD.name) — exercises every per-chip
# branch of main.py's BOARD table on a real import.
_CHIPS = [
    ("RP2040 with RP2040", "RP2040-Zero"),
    ("RP2350 with RP2350", "RP2350"),
    ("Generic ESP32S3 module with ESP32S3", "ESP32-S3-Zero"),
]


@pytest.mark.parametrize("machine_str,board_name", _CHIPS)
def test_main_executes_init_then_streams_one_frame(
    monkeypatch, fake_status, machine_str, board_name
):
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
    assert "scan" in diags
    assert "vl53l5cx_ok" in diags
    assert any("grid" in ln for ln in lines)


class _StopMainError(Exception):
    """Raised by the fake sensor on the second read() to escape stream()."""


class _Bus:
    """Minimal I²C bus stub: scans to the VL53L5CX fixed address."""

    @staticmethod
    def scan() -> list[int]:
        return [_TOF_ADDRESS]


class _FakeVL53L5CX:
    """Stub VL53L5CX driver; second read() raises to escape stream()."""

    def __init__(self, _bus) -> None:
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
    time_stub = SimpleNamespace(
        sleep_ms=lambda _ms: None,
        ticks_ms=lambda: 0,
    )
    boot_status_led_stub = SimpleNamespace(status=status_stub)
    # main() calls soft_i2c(BOARD.i2c), so the stub factory must be callable and
    # the package must expose the Wiring type main.py imports.
    i2c_bus_stub = SimpleNamespace(
        Wiring=collections.namedtuple("Wiring", ("id", "sda", "scl")),
        soft_i2c=lambda _wiring, **_kw: _Bus(),
    )
    vl53l5cx_stub = SimpleNamespace(VL53L5CX=_FakeVL53L5CX)

    return {
        "time": time_stub,
        "ujson": __import__("json"),
        "boot_status_led": boot_status_led_stub,
        "boot_status_led.status": status_stub,
        "i2c_bus": i2c_bus_stub,
        "vl53l5cx": vl53l5cx_stub,
    }
