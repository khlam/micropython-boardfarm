"""Host CPython end-to-end import test for oled-display firmware/main.py.

The AST-load fixture in conftest covers function bodies but skips module-level
imports and the trailing main() call. This test stubs sys.modules for every
external dependency and loads main.py as a real module; a fake canvas raises
after the first frame to escape render(), proving init → render is wired up.
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
OLED_ADDRESS = 0x3C


def test_main_runs_init_then_enters_render(monkeypatch, fake_status):
    for name, module in _build_stubs(fake_status).items():
        monkeypatch.setitem(sys.modules, name, module)
    # Earlier tests AST-exec main.py, leaving an entry in sys.modules.
    monkeypatch.delitem(sys.modules, "main", raising=False)

    spec = importlib.util.spec_from_file_location("main", _FIRMWARE)
    module = importlib.util.module_from_spec(spec)

    buf = io.StringIO()
    with redirect_stdout(buf), pytest.raises(_StopMainError):
        spec.loader.exec_module(module)

    lines = [json.loads(ln) for ln in buf.getvalue().splitlines() if ln.strip()]
    diags = [ln.get("diag") for ln in lines if "diag" in ln]
    assert "scan" in diags
    assert "oled_ok" in diags


class _StopMainError(Exception):
    """Raised by the fake canvas on the first show() to escape render()."""


class _Bus:
    """Minimal I²C bus stub: scans to the OLED address."""

    @staticmethod
    def scan() -> list[int]:
        return [OLED_ADDRESS]


class _FakeSSD1306:
    """Trivial SSD1306 stand-in; construction always succeeds."""

    def __init__(self, _i2c, _width, _height, _addr) -> None:
        self.addr = _addr


class _FakeCanvas:
    """OledCanvas stand-in; show() raises after the first frame draws."""

    def __init__(self, _driver, _width, _height) -> None:
        pass

    def clear(self) -> None:
        return None

    def fit_scale(self, _s, _max_w, _max_h) -> int:
        return 1

    def text_centered(self, _s, _cx, _cy, _scale) -> None:
        return None

    def show(self) -> None:
        raise _StopMainError


class _FakeBanner:
    """BouncingText stand-in with inert motion and a fixed position."""

    def __init__(self, _canvas, _s) -> None:
        self.x = 0
        self.y = 0

    def step(self) -> None:
        return None

    def draw(self) -> None:
        return None


def _build_stubs(status_stub):
    """Build SimpleNamespace stubs matching main.py's module-level imports."""
    time_stub = SimpleNamespace(
        sleep_ms=lambda _ms: None,
        ticks_ms=lambda: 0,
        ticks_diff=lambda a, b: a - b,
    )
    return {
        "time": time_stub,
        "ujson": __import__("json"),
        "boot_status_led": SimpleNamespace(status=status_stub),
        "boot_status_led.status": status_stub,
        "i2c_bus": SimpleNamespace(hard_i2c=_Bus()),
        "ssd1306": SimpleNamespace(SSD1306=_FakeSSD1306),
        "oled_canvas": SimpleNamespace(OledCanvas=_FakeCanvas, BouncingText=_FakeBanner),
    }
