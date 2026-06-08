"""Host CPython pytest bootstrap for the gps project firmware.

Exposes the `main_ns` fixture: an AST-loaded namespace with `emit`, `stream`,
and `main` extracted from main.py, and with fakes for `time`, `status`, and
`gps` injected so the streaming loop is exercisable without real hardware.
"""

from __future__ import annotations

import ast
import pathlib
from types import SimpleNamespace

import machine
import neopixel
import pytest

_HERE = pathlib.Path(__file__).parent.resolve()
_FIRMWARE = _HERE.parent / "firmware" / "main.py"
_KEEP_FUNCS = {"emit", "stream", "main"}


def _load_main_namespace(fake_time: object, fake_status: object) -> dict:
    """Parse main.py and exec constants + key functions in a fresh namespace.

    Import nodes and the trailing ``main()`` call are dropped so the loader
    does not block in the streaming loop. Callers seed ``time``, ``status``,
    and ``gps`` substitutes.
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
        # Placeholder — tests replace this with a _FakeGPS instance.
        "gps": None,
    }
    exec(code, ns)
    return ns


@pytest.fixture(autouse=True)
def _reset_devices() -> None:
    """Clear machine and neopixel state between tests."""
    machine.reset()
    neopixel.reset()


@pytest.fixture
def main_ns(fake_time: object, fake_status: object) -> SimpleNamespace:
    """Fresh AST-loaded main.py namespace with fakes injected.

    Returns a SimpleNamespace with:
        - .ns: dict of module-level names (pull stream, emit, …)
        - .time: the _FakeTime instance used as the `time` module
        - .status: the _FakeStatus instance; inspect .calls for transitions
    """
    ns = _load_main_namespace(fake_time, fake_status)
    return SimpleNamespace(ns=ns, time=fake_time, status=fake_status)
