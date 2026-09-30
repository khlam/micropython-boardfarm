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

import os
import pathlib
from collections import namedtuple
from types import SimpleNamespace

from micropython_stubs.testing import StopLoopError, firmware_namespace, run_stream
from vl53l0x import DeviceNotFoundError

_FIRMWARE = pathlib.Path(__file__).parent.parent / "firmware" / "main.py"
_KEEP_FUNCS = {"emit", "stream", "init_sensor"}
Board = namedtuple("Board", ("name", "sda", "scl"))
_TEST_BOARD = Board(name="RP2040-Zero", sda=0, scl=1)


def _make_main_ns() -> SimpleNamespace:
    """Create a fresh AST-loaded main.py namespace with fakes.

    Returns:
        The firmware functions and the fake status they report to.
    """
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
    """A read error stops then restarts ranging."""
    main_ns = _make_main_ns()
    tof = _FakeTof(script=[OSError])
    run_stream(main_ns, tof)
    assert tof.calls == ["stop", "start"]


def test_read_err_resets_filter_state():
    """The first good sample after a read error isn't blended with earlier ones."""
    main_ns = _make_main_ns()
    tof = _FakeTof(script=[100, 100, 100, OSError, 500])
    assert _distances(run_stream(main_ns, tof)) == [100, 100, 100, 500]


def test_inner_stop_start_failure_is_swallowed():
    """A failing stop() during recovery doesn't end the stream."""
    main_ns = _make_main_ns()
    tof = _FakeTof(script=[OSError, 200], stop_raises=OSError)
    assert _distances(run_stream(main_ns, tof)) == [200]


def test_status_transitions_around_read_err():
    """The status LED goes read_err on a fault and back to streaming after."""
    main_ns = _make_main_ns()
    tof = _FakeTof(script=[OSError, 100])
    run_stream(main_ns, tof)
    assert main_ns.status.calls == ["streaming", "read_err", "streaming"]


def test_out_of_range_emits_null_and_clears_state():
    """An out-of-range reading emits null, and the next sample isn't blended across it."""
    main_ns = _make_main_ns()
    tof = _FakeTof(script=[100, 8190, 200])
    assert _distances(run_stream(main_ns, tof)) == [100, None, 200]


def test_emits_raw_alongside_smoothed():
    """Each sample also carries the raw reading, null when out of range."""
    main_ns = _make_main_ns()
    tof = _FakeTof(script=[100, 8190, 200])
    lines = run_stream(main_ns, tof)
    raw = [ln["distance_mm_raw"] for ln in lines if "distance_mm_raw" in ln]
    assert raw == [100, None, 200]


def _distances(lines):
    return [ln["distance_mm"] for ln in lines if "distance_mm" in ln]


class _FakeTof:
    """Scripted VL53L0X stand-in.

    When the script is exhausted, read() raises StopLoopError to end the loop.

    Args:
        script: Items consumed in order on each read() call: an int is returned
            as the sample, and an exception *class* (OSError / RuntimeError) is raised.
        stop_raises: An exception class stop() raises, or None to stop cleanly.
    """

    def __init__(self, script: list, *, stop_raises: type[Exception] | None = None) -> None:
        self._script = list(script)
        self.calls: list[str] = []
        self._stop_raises = stop_raises

    def read(self):
        if not self._script:
            raise StopLoopError
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
