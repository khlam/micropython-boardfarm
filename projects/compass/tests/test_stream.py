"""Host CPython pytest tests for stream() in compass firmware.

Covers the happy path (one 8-key sample per loop with raw + smoothed axes,
heading in range), the smoothed-equals-raw warmup before the window fills, the
OVL edge-trigger ({"diag": "ovl"} only on rising edges of the STATUS overflow
bit), and read_err → streaming recovery.
"""

import math
import os
import pathlib
from collections import namedtuple
from types import SimpleNamespace

from micropython_stubs.testing import (
    StopLoopError,
    diags,
    firmware_namespace,
    run_stream,
    samples,
)
from qmc5883p import DeviceNotFoundError

_FIRMWARE = pathlib.Path(__file__).parent.parent / "firmware" / "main.py"
_KEEP_FUNCS = {"emit", "init_sensor", "stream"}
Board = namedtuple("Board", ("name", "i2c_id", "sda", "scl"))
_TEST_BOARD = Board(name="RP2040-Zero", i2c_id=0, sda=0, scl=1)

_OK = (100, -50, 200)


def _make_main_ns() -> SimpleNamespace:
    """Create a fresh AST-loaded main.py namespace with fakes.

    Returns:
        The firmware functions and the fake status they report to.
    """
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
    """Each read emits one sample carrying raw and smoothed axes plus the heading."""
    main_ns = _make_main_ns()
    mag = _FakeMag(script=[_OK])
    sample_lines = samples(run_stream(main_ns, mag))
    assert len(sample_lines) == 1
    assert set(sample_lines[0]) == {"t", "x", "y", "z", "xs", "ys", "zs", "heading_deg"}


def test_smoothed_equals_raw_until_window_fills():
    """Before the window fills, xs/ys/zs equal the raw x/y/z of that sample."""
    main_ns = _make_main_ns()
    mag = _FakeMag(script=[_OK])
    sample = samples(run_stream(main_ns, mag))[0]
    assert (sample["xs"], sample["ys"], sample["zs"]) == (
        sample["x"],
        sample["y"],
        sample["z"],
    )


def test_heading_normalised_to_circle():
    """The heading lies in [0, 360) degrees."""
    main_ns = _make_main_ns()
    mag = _FakeMag(script=[_OK])
    sample = samples(run_stream(main_ns, mag))[0]
    assert 0 <= sample["heading_deg"] < 360


def test_ovl_edge_triggers_once():
    """Three OVL-true reads emit exactly one {"diag": "ovl"} (rising edge only)."""
    main_ns = _make_main_ns()
    mag = _FakeMag(script=[_OK, _OK, _OK], ovl_script=[True, True, True])
    lines = run_stream(main_ns, mag)
    assert diags(lines).count("ovl") == 1


def test_ovl_falling_then_rising_emits_two():
    """OVL True → False → True emits two ovl events (two rising edges)."""
    main_ns = _make_main_ns()
    mag = _FakeMag(
        script=[_OK, _OK, _OK, _OK],
        ovl_script=[True, False, True, False],
    )
    lines = run_stream(main_ns, mag)
    assert diags(lines).count("ovl") == 2


def test_read_err_recovery_resumes_streaming():
    """A failed read reports read_err, and streaming resumes on the next good read."""
    main_ns = _make_main_ns()
    mag = _FakeMag(script=[_OK, OSError, _OK])
    lines = run_stream(main_ns, mag)
    assert len(samples(lines)) == 2
    assert "read_err" in diags(lines)
    assert main_ns.status.calls == ["streaming", "read_err", "streaming"]


class _FakeMag:
    """Scripted QMC5883P.

    Exhausting `script` raises StopLoopError.

    Args:
        script: Each item is a 3-tuple read() returns, or an exception class it raises.
        ovl_script: Consumed in lockstep with `script`; each entry sets
            last_status's OVL bit *after* the read returns. None never overflows.
    """

    def __init__(self, script: list, ovl_script: list[bool] | None = None) -> None:
        self._script = list(script)
        self._ovl = list(ovl_script or [False] * len(script))
        self.last_status = 0

    def read(self):
        if not self._script:
            raise StopLoopError
        item = self._script.pop(0)
        ovl = self._ovl.pop(0) if self._ovl else False
        if isinstance(item, type) and issubclass(item, BaseException):
            raise item("scripted")
        self.last_status = 0x02 if ovl else 0x00
        return item
