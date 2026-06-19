"""Host CPython pytest bootstrap for the clock project firmware.

Exposes the `main_ns` fixture: an AST-loaded namespace with the clock's
functions (`emit`, `_set_pixel`, `_snake_step`, `_run_window`, `run`, `main`)
and fakes for `time`/`status` plus the real shared helpers (`nmea`) injected.
"""

from __future__ import annotations

import ast
import os
import pathlib
import random
from collections import namedtuple
from types import SimpleNamespace

import machine
import neopixel
import pytest

from nmea import apply_parsed, build_utc_full, nmea_checksum_valid, parse_sentence

I2cBus = namedtuple("I2cBus", ("id", "sda", "scl"))
UartBus = namedtuple("UartBus", ("id", "tx", "rx"))
Device = namedtuple("Device", ("bus", "cs", "addr"))
DisplayWiring = namedtuple("DisplayWiring", ("spi_id", "sck", "mosi", "cs"))
Board = namedtuple("Board", ("name", "status_led", "i2c", "uart", "devices"))

_TEST_BOARD = Board(
    name="RP2040-Zero",
    status_led=16,
    i2c=I2cBus(id=0, sda=0, scl=1),
    uart=UartBus(id=1, tx=4, rx=5),
    devices={
        "gps": Device(bus="uart", cs=None, addr=None),
        "display_top": DisplayWiring(spi_id=1, sck=10, mosi=11, cs=9),
        "display_bot": DisplayWiring(spi_id=0, sck=6, mosi=7, cs=5),
    },
)

_HERE = pathlib.Path(__file__).parent.resolve()
_FIRMWARE = _HERE.parent / "firmware" / "main.py"

_KEEP_FUNCS = {
    "emit",
    "_set_pixel",
    "_snake_step",
    "_run_window",
    "run",
    "main",
}


def _load_main_namespace(fake_time: object, fake_status: object) -> dict:
    """Parse main.py and exec its constants + key functions in a fresh namespace.

    Import nodes and the trailing ``main()`` call are dropped so loading does not
    block in the run loop. The shared parser/offset helpers are injected so the
    AST-stripped ``from ... import`` lines do not leave them undefined.
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
        "os": os,
        "random": random,
        "namedtuple": namedtuple,
        "time": fake_time,
        "status": fake_status,
        "ujson": ujson,
        "BOARD": _TEST_BOARD,
        "nmea_checksum_valid": nmea_checksum_valid,
        "parse_sentence": parse_sentence,
        "apply_parsed": apply_parsed,
        "build_utc_full": build_utc_full,
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
        - .ns: dict of module-level names (emit, _set_pixel, _snake_step, etc.)
        - .time: the _FakeTime instance used as the `time` module
        - .status: the _FakeStatus instance; inspect .calls for transitions
    """
    ns = _load_main_namespace(fake_time, fake_status)
    return SimpleNamespace(ns=ns, time=fake_time, status=fake_status)
