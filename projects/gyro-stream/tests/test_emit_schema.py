"""Host CPython pytest checks for JSON schema invariants of gyro-stream's `emit()`.

Asserts the 8-key IMU sample dict round-trips and the diag namespace
(including the edge-triggered "sat" event) survives ujson.dumps. The
viz parser at projects/gyro-stream/viz/app.py drops non-JSON lines, so
a regression here silently breaks the dashboard.
"""

import ast
import io
import json
import os
import pathlib
from collections import namedtuple
from contextlib import redirect_stdout
from types import SimpleNamespace

from mpu6050 import DeviceNotFoundError

_FIRMWARE = pathlib.Path(__file__).parent.parent / "firmware" / "main.py"
_KEEP_FUNCS = {"emit", "init_sensor", "stream"}
Board = namedtuple("Board", ("name", "i2c_id", "sda", "scl"))
_TEST_BOARD = Board(name="RP2040-Zero", i2c_id=0, sda=0, scl=1)


def _make_main_ns():
    """Create a fresh AST-loaded main.py namespace with fakes."""
    src = _FIRMWARE.read_text()
    tree = ast.parse(src)
    kept = [
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        or (isinstance(node, ast.FunctionDef) and node.name in _KEEP_FUNCS)
    ]
    module = ast.Module(body=kept, type_ignores=[])
    ast.fix_missing_locations(module)
    code = compile(module, str(_FIRMWARE), "exec")

    import ujson

    ns: dict = {
        "time": SimpleNamespace(
            ticks=0, ticks_ms=lambda: 0, ticks_diff=lambda a, b: a - b, sleep_ms=lambda _ms: None
        ),
        "status": SimpleNamespace(),
        "ujson": ujson,
        "os": os,
        "namedtuple": namedtuple,
        "BOARD": _TEST_BOARD,
        "MPU6050": object,
        "DeviceNotFoundError": DeviceNotFoundError,
    }
    exec(code, ns)
    return ns


def test_emit_sample_dict():
    ns = _make_main_ns()
    emit = ns["emit"]
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


def test_emit_saturation_diag():
    ns = _make_main_ns()
    emit = ns["emit"]
    assert _run(emit, {"diag": "sat"}) == {"diag": "sat"}


def test_emit_diag_lines_are_valid_json():
    ns = _make_main_ns()
    emit = ns["emit"]
    parsed = _run(emit, {"diag": "scan", "devices": [0x68]})
    assert parsed["diag"] == "scan"
    assert parsed["devices"] == [104]


def _run(emit, obj):
    buf = io.StringIO()
    with redirect_stdout(buf):
        emit(obj)
    line = buf.getvalue().strip()
    return json.loads(line)
