"""Host CPython pytest bootstrap for the multizone-ranging firmware.

Exposes the `main_ns` fixture: an AST-loaded namespace containing main.py's
constants, emit(), init_sensor(), and stream(), with fakes for time and
status side effects so the streaming loop is exercisable in tests without
the module's top-level main() call running.
"""

import ast
import pathlib
from collections.abc import Callable
from types import SimpleNamespace

import pytest

_HERE = pathlib.Path(__file__).parent.resolve()
_FIRMWARE = _HERE.parent / "firmware" / "main.py"
_KEEP_FUNCS = {"emit", "stream", "init_sensor"}


class _FakeTime:
    """time stub: monotonic ticks_ms counter and no-op sleep_ms."""

    def __init__(self) -> None:
        self.ticks = 0

    def ticks_ms(self):
        self.ticks += 1
        return self.ticks

    def sleep_ms(self, _ms):
        return None


class _FakeStatus:
    """status stub: record every transition call by name into self.calls."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __getattr__(self, name: str) -> Callable[[], None]:
        if name.startswith("_"):
            raise AttributeError(name)

        def _rec() -> None:
            self.calls.append(name)

        return _rec


def _load_main_namespace(fake_time: _FakeTime, fake_status: _FakeStatus) -> dict:
    """Parse main.py and exec the constants + key functions in a fresh namespace.

    Keeps only module-level Assign nodes (constants) and the FunctionDefs the
    tests need. Drops Import nodes and the trailing Expr statement that calls
    main() — which would otherwise block in the ranging loop on import.
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

    ns: dict = {
        "time": fake_time,
        "status": fake_status,
        "ujson": ujson,
        # stream() has `tof: VL53L5CX` annotation; name must resolve at def time.
        "VL53L5CX": object,
    }
    exec(code, ns)
    return ns


@pytest.fixture
def main_ns():
    """Fresh AST-loaded main.py namespace with fakes injected.

    Returns a SimpleNamespace with:
      - .ns: dict of module-level names
      - .time: the _FakeTime instance used as the `time` module
      - .status: the _FakeStatus instance; inspect .status.calls for transitions
    """
    fake_time = _FakeTime()
    fake_status = _FakeStatus()
    ns = _load_main_namespace(fake_time, fake_status)
    return SimpleNamespace(ns=ns, time=fake_time, status=fake_status)
