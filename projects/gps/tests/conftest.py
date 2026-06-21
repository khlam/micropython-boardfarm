"""Host CPython pytest bootstrap for the gps project firmware.

Exposes the `main_ns` fixture: an AST-loaded namespace with `emit`, `stream`,
`_run_window`, and `main` extracted from main.py, and with fakes for `time`
and `status` injected.  Pure NMEA helpers live in nmea.py and are imported
directly in test_nmea.py; they are also injected into the exec namespace here
so that `_run_window` can resolve them at call time.
"""

from __future__ import annotations

import ast
import os
import pathlib
import sys
from collections import namedtuple
from types import SimpleNamespace

import machine
import neopixel
import pytest

_HERE = pathlib.Path(__file__).parent.resolve()
_FIRMWARE = _HERE.parent / "firmware" / "main.py"

# Add firmware/ to sys.path so `import nmea` works in test_nmea.py and here.
_FIRMWARE_DIR = str(_FIRMWARE.parent)
if _FIRMWARE_DIR not in sys.path:
    sys.path.insert(0, _FIRMWARE_DIR)

import nmea  # noqa: E402 — must follow sys.path setup above

_KEEP_FUNCS = {
    "emit",
    "stream",
    "main",
    "_run_window",
}

# Stand-in for main.py's BOARD. Tests drive stream()/_run_window() with a fake
# GPS directly and never call main(), so this only has to satisfy the kept
# namedtuple/_machine Assigns; the BOARD if/else is an ast.If and is dropped.
Wiring = namedtuple("Wiring", ("id", "tx", "rx"))
Board = namedtuple("Board", ("name", "gps"))
_TEST_BOARD = Board(name="RP2040-Zero", gps=Wiring(id=0, tx=0, rx=1))


def _load_main_namespace(fake_time: object, fake_status: object) -> dict:
    """Parse main.py and exec constants + key functions in a fresh namespace.

    Import nodes and the trailing ``main()`` call are dropped so the loader
    does not block in the streaming loop.  Callers seed ``time`` and ``status``
    substitutes; nmea helpers are injected so ``_run_window`` can resolve them.
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
        # main.py's BOARD dispatch is dropped by the AST filter; inject the
        # names its kept namedtuple/_machine Assigns need, plus a fixed BOARD.
        "os": os,
        "namedtuple": namedtuple,
        "BOARD": _TEST_BOARD,
        # Inject nmea helpers so _run_window can resolve them without the
        # `from nmea import ...` statement that the AST loader strips.
        "nmea_checksum_valid": nmea.nmea_checksum_valid,
        "parse_sentence": nmea.parse_sentence,
        "apply_parsed": nmea.apply_parsed,
        "build_utc_full": nmea.build_utc_full,
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
