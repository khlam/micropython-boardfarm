"""Host CPython pytest tests for stream() in gyro-stream firmware.

Covers the happy path, saturation edge-trigger ({"diag": "sat"} only on
rising edges of last_saturated), and read_err → streaming recovery.
"""

import os
import pathlib
from collections import namedtuple

from micropython_stubs.testing import (
    StopLoopError,
    diags,
    firmware_namespace,
    run_stream,
    samples,
)
from mpu6050 import DeviceNotFoundError

_FIRMWARE = pathlib.Path(__file__).parent.parent / "firmware" / "main.py"
_KEEP_FUNCS = {"emit", "init_sensor", "stream"}
Board = namedtuple("Board", ("name", "i2c_id", "sda", "scl"))
_TEST_BOARD = Board(name="RP2040-Zero", i2c_id=0, sda=0, scl=1)

_OK = (0.01, -0.02, 0.99, 0.1, -0.05, 0.0, 24.7)


def _make_main_ns():
    """Create a fresh AST-loaded main.py namespace with fakes."""
    return firmware_namespace(
        _FIRMWARE,
        _KEEP_FUNCS,
        os=os,
        namedtuple=namedtuple,
        BOARD=_TEST_BOARD,
        MPU6050=object,
        DeviceNotFoundError=DeviceNotFoundError,
    )


def test_one_sample_per_loop_with_full_8_keys():
    main_ns = _make_main_ns()
    imu = _FakeIMU(script=[_OK])
    sample_lines = samples(run_stream(main_ns, imu))
    assert len(sample_lines) == 1
    assert set(sample_lines[0]) == {"t", "ax", "ay", "az", "gx", "gy", "gz", "T"}


def test_saturation_edge_triggers_once():
    """Three sat-true reads emit exactly one {"diag": "sat"} (rising edge only)."""
    main_ns = _make_main_ns()
    imu = _FakeIMU(script=[_OK, _OK, _OK], sat_script=[True, True, True])
    lines = run_stream(main_ns, imu)
    assert diags(lines).count("sat") == 1


def test_saturation_falling_edge_emits_nothing():
    """sat: True → False → True emits two sat events (two rising edges)."""
    main_ns = _make_main_ns()
    imu = _FakeIMU(
        script=[_OK, _OK, _OK, _OK],
        sat_script=[True, False, True, False],
    )
    lines = run_stream(main_ns, imu)
    assert diags(lines).count("sat") == 2


def test_read_err_recovery_resumes_streaming():
    main_ns = _make_main_ns()
    imu = _FakeIMU(script=[_OK, OSError, _OK])
    lines = run_stream(main_ns, imu)
    assert samples(lines) and len(samples(lines)) == 2
    assert "read_err" in diags(lines)
    assert main_ns.status.calls == ["streaming", "read_err", "streaming"]


class _FakeIMU:
    """Scripted MPU6050.

    `script` items: 7-tuple = read_all() return; exception class = raise.
    `sat_script` is consumed in lockstep — each entry sets last_saturated
    *after* the read returns. Exhausting `script` raises StopLoopError.
    """

    def __init__(self, script, sat_script=None) -> None:
        self._script = list(script)
        self._sat = list(sat_script or [False] * len(script))
        self.last_saturated = False

    def read_all(self):
        if not self._script:
            raise StopLoopError
        item = self._script.pop(0)
        sat = self._sat.pop(0) if self._sat else False
        if isinstance(item, type) and issubclass(item, BaseException):
            raise item("scripted")
        self.last_saturated = sat
        return item
