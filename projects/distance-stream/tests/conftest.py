"""Host CPython pytest bootstrap for the distance-stream firmware.

Exposes the `main_ns` fixture: an AST-loaded namespace containing main.py's
constants, emit(), and stream(), with fakes for time and status side effects
so the streaming loop is exercisable in tests without the module's top-level
main() call running.
"""

import ast
import os
import pathlib
from collections import namedtuple
from types import SimpleNamespace

import pytest

_HERE = pathlib.Path(__file__).parent.resolve()
_FIRMWARE = _HERE.parent / "firmware" / "main.py"
_KEEP_FUNCS = {"emit", "stream", "soft_reset_sensor", "init_sensor"}

# Stand-in for main.py's BOARD. init_sensor() receives the bus directly in
# tests, so this only has to satisfy the kept namedtuple/_machine Assigns; the
# BOARD if/else is an ast.If and is dropped, so we inject a fixed record.
Wiring = namedtuple("Wiring", ("id", "sda", "scl"))
Board = namedtuple("Board", ("name", "i2c"))
_TEST_BOARD = Board(name="RP2040-Zero", i2c=Wiring(id=0, sda=0, scl=1))


def _load_main_namespace(fake_time, fake_status):
    """Parse main.py and exec the constants + key functions in a fresh namespace.

    Keeps only module-level Assign nodes (constants) and the FunctionDefs the
    tests need. Drops Import nodes (the caller seeds substitutes for `time`,
    `status`, `ujson`) and the trailing Expr statement that calls main() —
    which would otherwise block in the ranging loop on import.
    """
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

    from smoothing import median

    ns: dict = {
        "time": fake_time,
        "status": fake_status,
        "ujson": ujson,
        # main.py's BOARD dispatch is dropped by the AST filter; inject the
        # names its kept namedtuple/_machine Assigns need, plus a fixed BOARD.
        "os": os,
        "namedtuple": namedtuple,
        "BOARD": _TEST_BOARD,
        # The AST filter drops main.py's imports, so seed the real smoothing
        # function stream() calls; otherwise the name is unresolved at runtime.
        "median": median,
        # stream() has `tof: VL53L0X` in its signature; the annotation is
        # evaluated at def time, so the name must resolve. object suffices.
        "VL53L0X": object,
    }
    exec(code, ns)
    return ns


@pytest.fixture
def main_ns(fake_time, fake_status):
    """Fresh AST-loaded main.py namespace with fakes injected.

    Returns a SimpleNamespace with:
      - .ns: dict of module-level names (pull stream, emit, ...)
      - .time: the _FakeTime instance used as the `time` module
      - .status: the _FakeStatus instance; inspect .status.calls for transitions
    """
    ns = _load_main_namespace(fake_time, fake_status)
    return SimpleNamespace(ns=ns, time=fake_time, status=fake_status)
