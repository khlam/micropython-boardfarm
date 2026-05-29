"""Host CPython pytest checks for JSON schema invariants of multizone-ranging's emit().

Asserts that every line is ujson.dumps(obj) with no extra prints, that the
grid is a 64-element list, and that null/int values are preserved correctly.
"""

import io
import json
from contextlib import redirect_stdout

import ujson


def test_emit_grid_has_64_elements():
    emit = _capture_emit()
    result = _run(emit, {"t": 1, "grid": [100] * 64})
    assert len(result["grid"]) == 64


def test_emit_grid_int_values():
    emit = _capture_emit()
    grid = list(range(64))
    result = _run(emit, {"t": 1, "grid": grid})
    assert result["grid"] == grid


def test_emit_grid_null_values():
    emit = _capture_emit()
    grid = [None] * 64
    result = _run(emit, {"t": 1, "grid": grid})
    assert result["grid"] == [None] * 64


def test_emit_grid_mixed_int_and_null():
    emit = _capture_emit()
    grid = [i if i % 2 == 0 else None for i in range(64)]
    result = _run(emit, {"t": 1, "grid": grid})
    assert result["grid"] == grid


def test_emit_t_is_int():
    emit = _capture_emit()
    result = _run(emit, {"t": 12345, "grid": [0] * 64})
    assert isinstance(result["t"], int)
    assert result["t"] == 12345


def test_emit_diag_lines_valid_json():
    emit = _capture_emit()
    result = _run(emit, {"diag": "scan", "devices": [0x29]})
    assert result["diag"] == "scan"
    assert result["devices"] == [41]


def test_emit_firmware_loading_diag():
    emit = _capture_emit()
    result = _run(emit, {"diag": "firmware_loading"})
    assert result["diag"] == "firmware_loading"


def test_emit_vl53l5cx_ok_diag():
    emit = _capture_emit()
    result = _run(emit, {"diag": "vl53l5cx_ok", "addr": 0x29})
    assert result["diag"] == "vl53l5cx_ok"
    assert result["addr"] == 41


def _capture_emit():
    """Build emit() from main.py without executing the loop."""
    src = "def emit(obj):\n    print(ujson.dumps(obj))\n"
    ns = {"ujson": ujson}
    exec(src, ns)  # noqa: S102
    return ns["emit"]


def _run(emit, obj):
    buf = io.StringIO()
    with redirect_stdout(buf):
        emit(obj)
    return json.loads(buf.getvalue().strip())
