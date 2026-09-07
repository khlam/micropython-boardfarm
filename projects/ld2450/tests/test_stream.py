"""Host CPython integration tests for stream() in ld2450 firmware.

Drives stream() with a scripted fake radar and asserts:
  1. A report with targets emits one JSON line carrying t and a targets list;
  2. Zero targets (an empty tuple, not None) still emits "targets": [];
  3. Repeated None (timeout) reports emit exactly one report_timeout diag,
     latched until a report resumes;
  4. OSError emits a read_err diag every time (no latch), then recovers.
"""

import asyncio
import os
import pathlib
from collections import namedtuple
from math import atan2, degrees, sqrt

from micropython_stubs.testing import StopLoopError, firmware_namespace, run_async_stream

_FIRMWARE = pathlib.Path(__file__).parent.parent / "firmware" / "main.py"
_KEEP_FUNCS = {"emit", "stream", "_target_dict"}
Board = namedtuple("Board", ("name", "uart_id", "tx", "rx"))
_TEST_BOARD = Board(name="RP2040-Zero", uart_id=1, tx=4, rx=5)


class _Target:
    """Minimal stand-in for ld2450.Target — the five attributes _target_dict reads."""

    def __init__(self, slot, x_mm, y_mm, speed_cm_s, resolution_mm) -> None:
        self.slot = slot
        self.x_mm = x_mm
        self.y_mm = y_mm
        self.speed_cm_s = speed_cm_s
        self.resolution_mm = resolution_mm


class _FakeRadar:
    """Scripted LD2450 stand-in: read_latest() returns each script entry in turn."""

    def __init__(self, script) -> None:
        self._script = list(script)

    async def read_latest(self):
        if not self._script:
            raise StopLoopError
        outcome = self._script.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _make_main_ns():
    return firmware_namespace(
        _FIRMWARE,
        _KEEP_FUNCS,
        os=os,
        namedtuple=namedtuple,
        asyncio=asyncio,
        sqrt=sqrt,
        atan2=atan2,
        degrees=degrees,
    )


def test_stream_emits_targets_with_t_field():
    main_ns = _make_main_ns()
    target = _Target(1, 100, 200, 0, 50)
    radar = _FakeRadar([(target,)])
    lines = run_async_stream(main_ns, radar)
    data_lines = [ln for ln in lines if "targets" in ln]
    assert len(data_lines) == 1
    assert "t" in data_lines[0]
    assert data_lines[0]["targets"][0]["slot"] == 1


def test_stream_emits_empty_targets_list_for_no_active_targets():
    main_ns = _make_main_ns()
    radar = _FakeRadar([()])
    lines = run_async_stream(main_ns, radar)
    data_lines = [ln for ln in lines if "targets" in ln]
    assert len(data_lines) == 1
    assert data_lines[0]["targets"] == []


def test_stream_latches_single_report_timeout_diag():
    main_ns = _make_main_ns()
    radar = _FakeRadar([None, None, None, ()])
    lines = run_async_stream(main_ns, radar)
    diags = [ln["diag"] for ln in lines if "diag" in ln]
    assert diags.count("report_timeout") == 1
    assert main_ns.status.calls[-1] == "streaming"


def test_stream_read_err_emits_every_time_then_recovers():
    main_ns = _make_main_ns()
    radar = _FakeRadar([OSError("scripted"), OSError("scripted"), ()])
    lines = run_async_stream(main_ns, radar)
    diags = [ln["diag"] for ln in lines if "diag" in ln]
    assert diags.count("read_err") == 2
    assert main_ns.status.calls[-1] == "streaming"
