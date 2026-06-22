"""Host CPython pytest checks for JSON schema invariants of compass's `emit()`.

Asserts the 8-key magnetometer sample dict (raw x/y/z, smoothed xs/ys/zs, time,
heading) round-trips and the diag namespace (including the edge-triggered "ovl"
event) survives ujson.dumps. The viz parser at cpython-packages/serial_over_web
drops non-JSON lines, so a regression here silently breaks the dashboard.
"""

import ast
import io
import json
import math
import os
import pathlib
from collections import namedtuple
from contextlib import redirect_stdout
from types import SimpleNamespace

from qmc5883p import DeviceNotFoundError

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

    from smoothing import simple_moving_average

    ns: dict = {
        "time": SimpleNamespace(
            ticks=0, ticks_ms=lambda: 0, ticks_diff=lambda a, b: a - b, sleep_ms=lambda _ms: None
        ),
        "status": SimpleNamespace(),
        "ujson": ujson,
        "os": os,
        "namedtuple": namedtuple,
        "BOARD": _TEST_BOARD,
        "math": math,
        "simple_moving_average": simple_moving_average,
        "QMC5883P": object,
        "DeviceNotFoundError": DeviceNotFoundError,
    }
    exec(code, ns)
    return ns


def test_emit_sample_dict():
    ns = _make_main_ns()
    emit = ns["emit"]
    sample = {
        "t": 100,
        "x": 120,
        "y": -45,
        "z": 300,
        "xs": 118.5,
        "ys": -44.0,
        "zs": 301.25,
        "heading_deg": 200.5,
    }
    assert _run(emit, sample) == sample


def test_emit_ovl_diag():
    ns = _make_main_ns()
    emit = ns["emit"]
    assert _run(emit, {"diag": "ovl"}) == {"diag": "ovl"}


def test_emit_diag_lines_are_valid_json():
    ns = _make_main_ns()
    emit = ns["emit"]
    parsed = _run(emit, {"diag": "scan", "devices": [0x2C]})
    assert parsed["diag"] == "scan"
    assert parsed["devices"] == [44]


def _run(emit, obj):
    buf = io.StringIO()
    with redirect_stdout(buf):
        emit(obj)
    line = buf.getvalue().strip()
    return json.loads(line)
