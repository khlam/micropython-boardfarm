"""Host CPython pytest tests for stream() in compass firmware.

Covers the happy path (one 8-key sample per loop with raw + smoothed axes,
heading in range), the smoothed-equals-raw warmup before the window fills, the
OVL edge-trigger ({"diag": "ovl"} only on rising edges of the STATUS overflow
bit), and read_err → streaming recovery.
"""

import io
import json
import math
import os
import pathlib
from collections import namedtuple
from contextlib import redirect_stdout

import pytest

from micropython_stubs.testing import firmware_namespace
from qmc5883p import DeviceNotFoundError

_FIRMWARE = pathlib.Path(__file__).parent.parent / "firmware" / "main.py"
_KEEP_FUNCS = {"emit", "init_sensor", "stream"}
Board = namedtuple("Board", ("name", "i2c_id", "sda", "scl"))
_TEST_BOARD = Board(name="RP2040-Zero", i2c_id=0, sda=0, scl=1)

_OK = (100, -50, 200)


def _make_main_ns():
    """Create a fresh AST-loaded main.py namespace with fakes."""
    from smoothing import simple_moving_average

    return firmware_namespace(
        _FIRMWARE,
        _KEEP_FUNCS,
        os=os,
        namedtuple=namedtuple,
        BOARD=_TEST_BOARD,
        math=math,
        simple_moving_average=simple_moving_average,
        QMC5883P=object,
        DeviceNotFoundError=DeviceNotFoundError,
    )


def test_one_sample_per_loop_with_8_keys():
    main_ns = _make_main_ns()
    mag = _FakeMag(script=[_OK])
    samples = _samples(_run_stream(main_ns, mag))
    assert len(samples) == 1
    assert set(samples[0]) == {"t", "x", "y", "z", "xs", "ys", "zs", "heading_deg"}


def test_smoothed_equals_raw_until_window_fills():
    """Before the window fills, xs/ys/zs equal the raw x/y/z of that sample."""
    main_ns = _make_main_ns()
    mag = _FakeMag(script=[_OK])
    sample = _samples(_run_stream(main_ns, mag))[0]
    assert (sample["xs"], sample["ys"], sample["zs"]) == (
        sample["x"],
        sample["y"],
        sample["z"],
    )


def test_heading_normalised_to_circle():
    main_ns = _make_main_ns()
    mag = _FakeMag(script=[_OK])
    sample = _samples(_run_stream(main_ns, mag))[0]
    assert 0 <= sample["heading_deg"] < 360


def test_ovl_edge_triggers_once():
    """Three OVL-true reads emit exactly one {"diag": "ovl"} (rising edge only)."""
    main_ns = _make_main_ns()
    mag = _FakeMag(script=[_OK, _OK, _OK], ovl_script=[True, True, True])
    lines = _run_stream(main_ns, mag)
    assert _diags(lines).count("ovl") == 1


def test_ovl_falling_then_rising_emits_two():
    """OVL True → False → True emits two ovl events (two rising edges)."""
    main_ns = _make_main_ns()
    mag = _FakeMag(
        script=[_OK, _OK, _OK, _OK],
        ovl_script=[True, False, True, False],
    )
    lines = _run_stream(main_ns, mag)
    assert _diags(lines).count("ovl") == 2


def test_read_err_recovery_resumes_streaming():
    main_ns = _make_main_ns()
    mag = _FakeMag(script=[_OK, OSError, _OK])
    lines = _run_stream(main_ns, mag)
    assert len(_samples(lines)) == 2
    assert "read_err" in _diags(lines)
    assert main_ns.status.calls == ["streaming", "read_err", "streaming"]


def _run_stream(main_ns, mag):
    stream = main_ns.ns["stream"]
    buf = io.StringIO()
    with redirect_stdout(buf), pytest.raises(_StopLoopError):
        stream(mag)
    return [json.loads(ln) for ln in buf.getvalue().splitlines() if ln.strip()]


def _samples(lines):
    return [ln for ln in lines if "diag" not in ln]


def _diags(lines):
    return [ln["diag"] for ln in lines if "diag" in ln]


class _StopLoopError(Exception):
    """Sentinel: any non-OSError raised by the fake mag escapes the loop."""


class _FakeMag:
    """Scripted QMC5883P.

    `script` items: 3-tuple = read() return; exception class = raise.
    `ovl_script` is consumed in lockstep — each entry sets last_status's OVL bit
    *after* the read returns. Exhausting `script` raises _StopLoopError.
    """

    def __init__(self, script, ovl_script=None) -> None:
        self._script = list(script)
        self._ovl = list(ovl_script or [False] * len(script))
        self.last_status = 0

    def read(self):
        if not self._script:
            raise _StopLoopError
        item = self._script.pop(0)
        ovl = self._ovl.pop(0) if self._ovl else False
        if isinstance(item, type) and issubclass(item, BaseException):
            raise item("scripted")
        self.last_status = 0x02 if ovl else 0x00
        return item
