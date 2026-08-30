"""Host CPython end-to-end import test for ld2450 firmware/main.py.

The AST-load fixture in the other test files covers function bodies but
skips module-level imports and the trailing asyncio.run(main()) call. This
test stubs sys.modules for every external dependency and loads main.py as a
real module — exercising each per-chip BOARD branch — while a fake driver
raises after one report to escape stream() via asyncio.run(main()).
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


class _StopMainError(Exception):
    """Raised by the fake radar's second read_latest() to escape stream()."""


@pytest.mark.parametrize("machine_str,board_name", BOARD_CHIPS)
def test_main_executes_init_then_streams_one_frame(monkeypatch, machine_str, board_name):
    fake_status = FakeStatus()
    closed = []

    class _FakeLD2450:
        """Stub driver that opens its own UART; second read_latest() escapes stream()."""

        def __init__(self, model, *, bus_id, tx, rx) -> None:
            self._calls = 0

        async def wait_ready(self) -> None:
            return None

        async def read_latest(self):
            self._calls += 1
            if self._calls > 1:
                raise _StopMainError
            return ()

        def close(self) -> None:
            closed.append(self)

    monkeypatch.setattr(os, "uname", lambda: SimpleNamespace(machine=machine_str))
    radar_stub = SimpleNamespace(
        driver=_FakeLD2450,
        Model=SimpleNamespace(LD2450="ld2450"),
        ReportStream=object,
        DeviceNotFoundError=DeviceNotFoundError,
    )
    for name, module in build_full_import_stubs("radar", radar_stub, fake_status).items():
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
    assert "radar_ok" in diags
    assert any("targets" in ln for ln in lines)
    assert len(closed) == 1
