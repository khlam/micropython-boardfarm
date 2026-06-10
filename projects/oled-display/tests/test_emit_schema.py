"""Host CPython pytest checks for JSON schema invariants of oled-display's `emit()`.

Asserts that emit() produces one valid `ujson.dumps(obj)` line with no extra
prints — any raw print() would corrupt the JSON-over-USB stream a host reader
parses. Covers both per-second counter records and diagnostic lines.
"""

import io
import json
from contextlib import redirect_stdout


def test_emit_counter_record_round_trips(main_ns):
    emit = main_ns.ns["emit"]
    record = {"t": 1023, "count": 1, "x": 10, "y": 5}
    parsed = _run(emit, record)
    assert parsed == record
    assert isinstance(parsed["count"], int)


def test_emit_diag_line_is_valid_json(main_ns):
    emit = main_ns.ns["emit"]
    parsed = _run(emit, {"diag": "oled_ok", "addr": 0x3C})
    assert parsed["diag"] == "oled_ok"
    assert parsed["addr"] == 60


def _run(emit, obj):
    buf = io.StringIO()
    with redirect_stdout(buf):
        emit(obj)
    line = buf.getvalue().strip()
    return json.loads(line)
