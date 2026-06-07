"""Host CPython pytest bootstrap for the distance-stream firmware.

Exposes the `main_ns` fixture: an AST-loaded namespace containing main.py's
constants, emit(), and stream(), with fakes for time and status side effects
so the streaming loop is exercisable in tests without the module's top-level
main() call running.
"""

import ast
import pathlib
from types import SimpleNamespace

import pytest

_HERE = pathlib.Path(__file__).parent.resolve()
_FIRMWARE = _HERE.parent / "firmware" / "main.py"
_KEEP_FUNCS = {"emit", "stream", "soft_reset_sensor", "init_sensor"}


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
