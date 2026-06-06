"""Host CPython pytest checks for JSON schema invariants of compass's `emit()`.

Asserts the 5-key magnetometer sample dict round-trips and the diag namespace
(including the edge-triggered "ovl" event) survives ujson.dumps. The viz parser
at cpython-packages/serial_over_web drops non-JSON lines, so a regression here
silently breaks the dashboard.
"""

import io
import json
from contextlib import redirect_stdout


def test_emit_sample_dict(main_ns):
    emit = main_ns.ns["emit"]
    sample = {"t": 100, "x": 120, "y": -45, "z": 300, "heading_deg": 200.5}
    assert _run(emit, sample) == sample


def test_emit_ovl_diag(main_ns):
    emit = main_ns.ns["emit"]
    assert _run(emit, {"diag": "ovl"}) == {"diag": "ovl"}


def test_emit_diag_lines_are_valid_json(main_ns):
    emit = main_ns.ns["emit"]
    parsed = _run(emit, {"diag": "scan", "devices": [0x2C]})
    assert parsed["diag"] == "scan"
    assert parsed["devices"] == [44]


def _run(emit, obj):
    buf = io.StringIO()
    with redirect_stdout(buf):
        emit(obj)
    line = buf.getvalue().strip()
    return json.loads(line)
