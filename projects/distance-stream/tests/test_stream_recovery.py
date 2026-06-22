"""Host CPython integration tests for stream() recovery and out-of-range paths in distance-stream.

Drives stream() with a scripted fake VL53L0X, and asserts the four safety-critical
behaviors of the read-error branch plus the out-of-range gap branch:

  1. stop() then start() are called, in that order, after a transient fault;
  2. the smoothing window is cleared so the next good sample starts fresh;
  3. the inner stop/start try/except swallows its own faults so the outer
     loop survives a double fault;
  4. the LED transitions read_err -> streaming around the fault;
  5. out-of-range readings emit `distance_mm: null` and clear the window
     so the next in-range sample restarts rather than blending across the gap.
"""

import io
import json
import os
import pathlib
from collections import namedtuple
from contextlib import redirect_stdout

import pytest

from micropython_stubs.testing import firmware_namespace
from vl53l0x import DeviceNotFoundError

_FIRMWARE = pathlib.Path(__file__).parent.parent / "firmware" / "main.py"
_KEEP_FUNCS = {"emit", "stream", "init_sensor"}
Board = namedtuple("Board", ("name", "sda", "scl"))
_TEST_BOARD = Board(name="RP2040-Zero", sda=0, scl=1)


def _make_main_ns():
    """Create a fresh AST-loaded main.py namespace with fakes."""
    from smoothing import median

    return firmware_namespace(
        _FIRMWARE,
        _KEEP_FUNCS,
        os=os,
        namedtuple=namedtuple,
        BOARD=_TEST_BOARD,
        median=median,
        VL53L0X=object,
        DeviceNotFoundError=DeviceNotFoundError,
    )


def test_read_err_calls_stop_then_start_in_order():
    main_ns = _make_main_ns()
    tof = _FakeTof(script=[OSError])
    _run_stream(main_ns, tof)
    assert tof.calls == ["stop", "start"]


def test_read_err_resets_filter_state():
    main_ns = _make_main_ns()
    tof = _FakeTof(script=[100, 100, 100, OSError, 500])
    assert _distances(_run_stream(main_ns, tof)) == [100, 100, 100, 500]


def test_inner_stop_start_failure_is_swallowed():
    main_ns = _make_main_ns()
    tof = _FakeTof(script=[OSError, 200], stop_raises=OSError)
    assert _distances(_run_stream(main_ns, tof)) == [200]


def test_status_transitions_around_read_err():
    main_ns = _make_main_ns()
    tof = _FakeTof(script=[OSError, 100])
    _run_stream(main_ns, tof)
    assert main_ns.status.calls == ["streaming", "read_err", "streaming"]


def test_out_of_range_emits_null_and_clears_state():
    main_ns = _make_main_ns()
    tof = _FakeTof(script=[100, 8190, 200])
    assert _distances(_run_stream(main_ns, tof)) == [100, None, 200]


def test_emits_raw_alongside_smoothed():
    main_ns = _make_main_ns()
    tof = _FakeTof(script=[100, 8190, 200])
    lines = _run_stream(main_ns, tof)
    raw = [ln["distance_mm_raw"] for ln in lines if "distance_mm_raw" in ln]
    assert raw == [100, None, 200]


def _run_stream(main_ns, fake_tof):
    """Drive stream() until the fake's script is exhausted; return parsed JSON lines."""
    stream = main_ns.ns["stream"]
    buf = io.StringIO()
    with redirect_stdout(buf), pytest.raises(_StopLoopError):
        stream(fake_tof)
    return [json.loads(line) for line in buf.getvalue().splitlines() if line.strip()]


def _distances(lines):
    return [ln["distance_mm"] for ln in lines if "distance_mm" in ln]


class _StopLoopError(Exception):
    """Sentinel exception used by the fake tof to escape the streaming loop."""


class _FakeTof:
    """Scripted VL53L0X stand-in.

    `script` is a list of items consumed in order on each read() call:
      - an int  -> returned as the sample
      - an exception *class* (OSError / RuntimeError) -> raised
    When the script is exhausted, read() raises _StopLoopError to end the loop.
    """

    def __init__(self, script, *, stop_raises=None) -> None:
        self._script = list(script)
        self.calls: list[str] = []
        self._stop_raises = stop_raises

    def read(self):
        if not self._script:
            raise _StopLoopError
        item = self._script.pop(0)
        if isinstance(item, type) and issubclass(item, BaseException):
            raise item("scripted")
        return item

    def stop(self):
        self.calls.append("stop")
        if self._stop_raises is not None:
            raise self._stop_raises("scripted stop")

    def start(self):
        self.calls.append("start")
