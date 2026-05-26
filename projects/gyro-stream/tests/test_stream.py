"""Host CPython pytest tests for stream() in gyro-stream firmware.

Covers the happy path, saturation edge-trigger ({"diag": "sat"} only on
rising edges of last_saturated), and read_err → streaming recovery.
"""

import io
import json
from contextlib import redirect_stdout

import pytest

_OK = (0.01, -0.02, 0.99, 0.1, -0.05, 0.0, 24.7)


def test_one_sample_per_loop_with_full_8_keys(main_ns):
    imu = _FakeIMU(script=[_OK])
    samples = _samples(_run_stream(main_ns, imu))
    assert len(samples) == 1
    assert set(samples[0]) == {"t", "ax", "ay", "az", "gx", "gy", "gz", "T"}


def test_saturation_edge_triggers_once(main_ns):
    """Three sat-true reads emit exactly one {"diag": "sat"} (rising edge only)."""
    imu = _FakeIMU(script=[_OK, _OK, _OK], sat_script=[True, True, True])
    lines = _run_stream(main_ns, imu)
    assert _diags(lines).count("sat") == 1


def test_saturation_falling_edge_emits_nothing(main_ns):
    """sat: True → False → True emits two sat events (two rising edges)."""
    imu = _FakeIMU(
        script=[_OK, _OK, _OK, _OK],
        sat_script=[True, False, True, False],
    )
    lines = _run_stream(main_ns, imu)
    assert _diags(lines).count("sat") == 2


def test_read_err_recovery_resumes_streaming(main_ns):
    imu = _FakeIMU(script=[_OK, OSError, _OK])
    lines = _run_stream(main_ns, imu)
    assert _samples(lines) and len(_samples(lines)) == 2
    assert "read_err" in _diags(lines)
    assert main_ns.status.calls == ["streaming", "read_err", "streaming"]


def _run_stream(main_ns, imu):
    stream = main_ns.ns["stream"]
    buf = io.StringIO()
    with redirect_stdout(buf), pytest.raises(_StopLoopError):
        stream(imu)
    return [json.loads(ln) for ln in buf.getvalue().splitlines() if ln.strip()]


def _samples(lines):
    return [ln for ln in lines if "diag" not in ln]


def _diags(lines):
    return [ln["diag"] for ln in lines if "diag" in ln]


class _StopLoopError(Exception):
    """Sentinel: any non-OSError raised by the fake IMU escapes the loop."""


class _FakeIMU:
    """Scripted MPU6050.

    `script` items: 7-tuple = read_all() return; exception class = raise.
    `sat_script` is consumed in lockstep — each entry sets last_saturated
    *after* the read returns. Exhausting `script` raises _StopLoopError.
    """

    def __init__(self, script, sat_script=None) -> None:
        self._script = list(script)
        self._sat = list(sat_script or [False] * len(script))
        self.last_saturated = False

    def read_all(self):
        if not self._script:
            raise _StopLoopError
        item = self._script.pop(0)
        sat = self._sat.pop(0) if self._sat else False
        if isinstance(item, type) and issubclass(item, BaseException):
            raise item("scripted")
        self.last_saturated = sat
        return item
