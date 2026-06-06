"""Host CPython pytest tests for stream() in compass firmware.

Covers the happy path (one 5-key sample per loop, heading in range), the OVL
edge-trigger ({"diag": "ovl"} only on rising edges of the STATUS overflow bit),
and read_err → streaming recovery.
"""

import io
import json
from contextlib import redirect_stdout

import pytest

_OK = (100, -50, 200)


def test_one_sample_per_loop_with_5_keys(main_ns):
    mag = _FakeMag(script=[_OK])
    samples = _samples(_run_stream(main_ns, mag))
    assert len(samples) == 1
    assert set(samples[0]) == {"t", "x", "y", "z", "heading_deg"}


def test_heading_normalised_to_circle(main_ns):
    mag = _FakeMag(script=[_OK])
    sample = _samples(_run_stream(main_ns, mag))[0]
    assert 0 <= sample["heading_deg"] < 360


def test_ovl_edge_triggers_once(main_ns):
    """Three OVL-true reads emit exactly one {"diag": "ovl"} (rising edge only)."""
    mag = _FakeMag(script=[_OK, _OK, _OK], ovl_script=[True, True, True])
    lines = _run_stream(main_ns, mag)
    assert _diags(lines).count("ovl") == 1


def test_ovl_falling_then_rising_emits_two(main_ns):
    """OVL True → False → True emits two ovl events (two rising edges)."""
    mag = _FakeMag(
        script=[_OK, _OK, _OK, _OK],
        ovl_script=[True, False, True, False],
    )
    lines = _run_stream(main_ns, mag)
    assert _diags(lines).count("ovl") == 2


def test_read_err_recovery_resumes_streaming(main_ns):
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
