"""Host CPython integration tests for stream() in multizone-ranging firmware.

Drives stream() with a scripted fake VL53L5CX and asserts:
  1. No emit when check_data_ready returns False;
  2. Grid emitted when check_data_ready returns True;
  3. OSError/RuntimeError routed to status.read_err() with recovery;
  4. stop() then start() are called in order after a fault;
  5. The loop survives a double-fault in the inner stop/start recovery.
"""

import io
import json
from contextlib import redirect_stdout

import pytest


def test_stream_no_emit_when_data_not_ready(main_ns):
    tof = _FakeTof(script=[False])
    lines = _run_stream(main_ns, tof)
    data_lines = [ln for ln in lines if "grid" in ln]
    assert data_lines == []


def test_stream_emits_grid_when_data_ready(main_ns):
    grid = list(range(64))
    tof = _FakeTof(script=[True], grids=[grid])
    lines = _run_stream(main_ns, tof)
    data_lines = [ln for ln in lines if "grid" in ln]
    assert len(data_lines) == 1
    assert data_lines[0]["grid"] == grid


def test_stream_grid_has_t_field(main_ns):
    tof = _FakeTof(script=[True], grids=[[0] * 64])
    lines = _run_stream(main_ns, tof)
    grid_lines = [ln for ln in lines if "grid" in ln]
    assert "t" in grid_lines[0]


def test_stream_read_err_calls_status_read_err(main_ns):
    tof = _FakeTof(script=[True], read_raises=OSError)
    _run_stream(main_ns, tof)
    assert "read_err" in main_ns.status.calls


def test_stream_runtime_err_calls_status_read_err(main_ns):
    tof = _FakeTof(script=[True], read_raises=RuntimeError)
    _run_stream(main_ns, tof)
    assert "read_err" in main_ns.status.calls


def test_stream_read_err_calls_stop_then_start(main_ns):
    tof = _FakeTof(script=[True], read_raises=OSError)
    _run_stream(main_ns, tof)
    assert tof.calls == ["stop", "start"]


def test_stream_inner_stop_raises_is_swallowed(main_ns):
    tof = _FakeTof(script=[True, True], read_raises=OSError, stop_raises=OSError)
    _run_stream(main_ns, tof)
    assert "read_err" in main_ns.status.calls
    assert tof.calls == ["stop", "stop"]


def test_stream_recovers_and_emits_after_error(main_ns):
    grid = [50] * 64
    tof = _FakeTof(script=[True, True], grids=[grid], read_raises_once=True)
    lines = _run_stream(main_ns, tof)
    grid_lines = [ln for ln in lines if "grid" in ln]
    assert len(grid_lines) == 1
    assert grid_lines[0]["grid"] == grid


def test_stream_status_transitions(main_ns):
    tof = _FakeTof(script=[True], read_raises=OSError)
    _run_stream(main_ns, tof)
    assert main_ns.status.calls == ["streaming", "read_err", "streaming"]


def _run_stream(main_ns, fake_tof):
    """Drive stream() until the fake's script is exhausted; return parsed JSON lines."""
    stream = main_ns.ns["stream"]
    buf = io.StringIO()
    with redirect_stdout(buf), pytest.raises(_StopLoopError):
        stream(fake_tof)
    return [json.loads(line) for line in buf.getvalue().splitlines() if line.strip()]


class _StopLoopError(Exception):
    """Sentinel: propagates out of stream() to end the test."""


class _FakeTof:
    """Scripted VL53L5CX stand-in.

    `script` is consumed by check_data_ready() in order:
      - True  → data ready; read() will be called
      - False → not ready; stream() sleeps and continues

    `grids` is consumed by read() in order when check_data_ready() returns True.
    When script or grids are exhausted, raises _StopLoopError to end the loop.

    `read_raises` makes every read() call raise that exception class.
    `read_raises_once` makes only the first read() raise OSError;
        subsequent calls consume from grids.
    `stop_raises` makes stop() raise.
    """

    def __init__(
        self,
        script,
        grids=None,
        *,
        read_raises=None,
        read_raises_once=False,
        stop_raises=None,
    ) -> None:
        self._script = list(script)
        self._grids = list(grids or [])
        self._read_raises = read_raises
        self._read_raises_once = read_raises_once
        self._first_read = True
        self._stop_raises = stop_raises
        self.calls: list[str] = []

    def check_data_ready(self) -> bool:
        if not self._script:
            raise _StopLoopError
        return self._script.pop(0)

    def read(self) -> list:
        if self._read_raises is not None:
            raise self._read_raises("scripted read error")
        if self._read_raises_once and self._first_read:
            self._first_read = False
            raise OSError("scripted first-read error")
        if not self._grids:
            raise _StopLoopError
        return self._grids.pop(0)

    def stop(self) -> None:
        self.calls.append("stop")
        if self._stop_raises is not None:
            raise self._stop_raises("scripted stop")

    def start(self, _freq=10) -> None:
        self.calls.append("start")
