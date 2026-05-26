"""Host CPython pytest checks for JSON schema invariants of gyro-stream's `emit()`.

Asserts the 8-key IMU sample dict round-trips and the diag namespace
(including the edge-triggered "sat" event) survives ujson.dumps. The
viz parser at projects/gyro-stream/viz/app.py drops non-JSON lines, so
a regression here silently breaks the dashboard.
"""

import io
import json
from contextlib import redirect_stdout


def test_emit_sample_dict(main_ns):
    emit = main_ns.ns["emit"]
    sample = {
        "t": 100,
        "ax": 0.01,
        "ay": -0.02,
        "az": 0.99,
        "gx": 0.1,
        "gy": -0.05,
        "gz": 0.0,
        "T": 24.7,
    }
    assert _run(emit, sample) == sample


def test_emit_saturation_diag(main_ns):
    emit = main_ns.ns["emit"]
    assert _run(emit, {"diag": "sat"}) == {"diag": "sat"}


def test_emit_diag_lines_are_valid_json(main_ns):
    emit = main_ns.ns["emit"]
    parsed = _run(emit, {"diag": "scan", "devices": [0x68]})
    assert parsed["diag"] == "scan"
    assert parsed["devices"] == [104]


def _run(emit, obj):
    buf = io.StringIO()
    with redirect_stdout(buf):
        emit(obj)
    line = buf.getvalue().strip()
    return json.loads(line)
