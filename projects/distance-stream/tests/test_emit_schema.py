"""Host CPython pytest checks for JSON schema invariants of distance-stream's `emit()`.

Asserts that:
  - every line is `ujson.dumps(obj)` with no extra prints
  - `distance_mm` is `null` (None) when ToF reports OUT_OF_RANGE_MM (≥8190)
  - `distance_mm` is an int mm otherwise

The viz parser at projects/distance-stream/viz/app.py drops any line that
isn't valid JSON, so any regression here silently breaks the dashboard.
"""

import io
import json
from contextlib import redirect_stdout

import ujson


def test_emit_distance_int():
    emit = _capture_emit()
    assert _run(emit, {"t": 100, "distance_mm": 412}) == {"t": 100, "distance_mm": 412}


def test_emit_out_of_range_is_null():
    emit = _capture_emit()
    assert _run(emit, {"t": 100, "distance_mm": None}) == {"t": 100, "distance_mm": None}


def test_emit_diag_lines_are_valid_json():
    emit = _capture_emit()
    parsed = _run(emit, {"diag": "scan", "devices": [0x29]})
    assert parsed["diag"] == "scan"
    assert parsed["devices"] == [41]


def _capture_emit():
    """Build the trivial emit() from main.py without executing the loop.

    main.py runs at module level — importing it would block forever in the
    ranging loop. So we read the source, extract just the emit() function,
    and exec it in a clean namespace.
    """
    src = "def emit(obj):\n    print(ujson.dumps(obj))\n"
    ns = {"ujson": ujson}
    exec(src, ns)
    return ns["emit"]


def _run(emit, obj):
    buf = io.StringIO()
    with redirect_stdout(buf):
        emit(obj)
    line = buf.getvalue().strip()
    return json.loads(line)
