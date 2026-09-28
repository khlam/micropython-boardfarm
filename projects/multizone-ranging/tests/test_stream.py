"""Host CPython integration tests for stream() in multizone-ranging firmware.

Drives stream() with a scripted fake VL53L5CX and asserts:
  1. No emit when check_data_ready returns False;
  2. Grid emitted when check_data_ready returns True;
  3. OSError/RuntimeError routed to status.read_err() with recovery;
  4. stop() then start() are called in order after a fault;
  5. The loop survives a double-fault in the inner stop/start recovery.
"""

import os
import pathlib
from collections import namedtuple
from types import SimpleNamespace

from micropython_stubs.testing import StopLoopError, firmware_namespace, run_stream
from vl53l5cx import DeviceNotFoundError

_FIRMWARE = pathlib.Path(__file__).parent.parent / "firmware" / "main.py"
_KEEP_FUNCS = {"emit", "stream", "init_sensor"}
Board = namedtuple("Board", ("name", "sda", "scl"))
_TEST_BOARD = Board(name="RP2040-Zero", sda=0, scl=1)


def _make_main_ns() -> SimpleNamespace:
    """Create a fresh AST-loaded main.py namespace with fakes.

    Returns:
        The firmware functions and the fake status they report to.
    """
    return firmware_namespace(
        _FIRMWARE,
        _KEEP_FUNCS,
        os=os,
        namedtuple=namedtuple,
        BOARD=_TEST_BOARD,
        VL53L5CX=object,
        DeviceNotFoundError=DeviceNotFoundError,
    )


def test_stream_no_emit_when_data_not_ready():
    """Nothing is emitted while the sensor has no new data."""
    main_ns = _make_main_ns()
    tof = _FakeTof(script=[False])
    lines = run_stream(main_ns, tof)
    data_lines = [ln for ln in lines if "grid" in ln]
    assert data_lines == []


def test_stream_emits_grid_when_data_ready():
    """New data is emitted as one grid line carrying the zones read."""
    main_ns = _make_main_ns()
    grid = list(range(64))
    tof = _FakeTof(script=[True], grids=[grid])
    lines = run_stream(main_ns, tof)
    data_lines = [ln for ln in lines if "grid" in ln]
    assert len(data_lines) == 1
    assert data_lines[0]["grid"] == grid


def test_stream_grid_has_t_field():
    """Each grid line carries a timestamp."""
    main_ns = _make_main_ns()
    tof = _FakeTof(script=[True], grids=[[0] * 64])
    lines = run_stream(main_ns, tof)
    grid_lines = [ln for ln in lines if "grid" in ln]
    assert "t" in grid_lines[0]


def test_stream_read_err_calls_status_read_err():
    """An OSError from read() shows read_err."""
    main_ns = _make_main_ns()
    tof = _FakeTof(script=[True], read_raises=OSError)
    run_stream(main_ns, tof)
    assert "read_err" in main_ns.status.calls


def test_stream_runtime_err_calls_status_read_err():
    """A RuntimeError from read() shows read_err."""
    main_ns = _make_main_ns()
    tof = _FakeTof(script=[True], read_raises=RuntimeError)
    run_stream(main_ns, tof)
    assert "read_err" in main_ns.status.calls


def test_stream_read_err_calls_stop_then_start():
    """A read error stops then restarts ranging."""
    main_ns = _make_main_ns()
    tof = _FakeTof(script=[True], read_raises=OSError)
    run_stream(main_ns, tof)
    assert tof.calls == ["stop", "start"]


def test_stream_inner_stop_raises_is_swallowed():
    """A failing stop() during recovery doesn't end the stream."""
    main_ns = _make_main_ns()
    tof = _FakeTof(script=[True, True], read_raises=OSError, stop_raises=OSError)
    run_stream(main_ns, tof)
    assert "read_err" in main_ns.status.calls
    assert tof.calls == ["stop", "stop"]


def test_stream_recovers_and_emits_after_error():
    """After one read error, the next ready grid is emitted."""
    main_ns = _make_main_ns()
    grid = [50] * 64
    tof = _FakeTof(script=[True, True], grids=[grid], read_raises_once=True)
    lines = run_stream(main_ns, tof)
    grid_lines = [ln for ln in lines if "grid" in ln]
    assert len(grid_lines) == 1
    assert grid_lines[0]["grid"] == grid


def test_stream_status_transitions():
    """The status LED goes read_err on a fault and back to streaming after."""
    main_ns = _make_main_ns()
    tof = _FakeTof(script=[True], read_raises=OSError)
    run_stream(main_ns, tof)
    assert main_ns.status.calls == ["streaming", "read_err", "streaming"]


class _FakeTof:
    """Scripted VL53L5CX stand-in.

    Args:
        script: What each check_data_ready() call returns; exhausting it raises
            StopLoopError.
        grids: What each read() call returns; exhausting it raises StopLoopError.
        read_raises: An exception class every read() raises, or None.
        read_raises_once: Whether the first read() raises OSError.
        stop_raises: An exception class stop() raises, or None to stop cleanly.
    """

    def __init__(
        self,
        script: list[bool],
        grids: list[list[int]] | None = None,
        *,
        read_raises: type[Exception] | None = None,
        read_raises_once: bool = False,
        stop_raises: type[Exception] | None = None,
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
            raise StopLoopError
        return self._script.pop(0)

    def read(self) -> list:
        if self._read_raises is not None:
            raise self._read_raises("scripted read error")
        if self._read_raises_once and self._first_read:
            self._first_read = False
            raise OSError("scripted first-read error")
        if not self._grids:
            raise StopLoopError
        return self._grids.pop(0)

    def stop(self) -> None:
        self.calls.append("stop")
        if self._stop_raises is not None:
            raise self._stop_raises("scripted stop")

    def start(self, _freq=10) -> None:
        self.calls.append("start")
