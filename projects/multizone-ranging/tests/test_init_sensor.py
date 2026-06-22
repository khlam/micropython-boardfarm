"""Host CPython pytest tests for init_sensor() in multizone-ranging firmware.

The driver opens its own bus and scans, so init_sensor() takes no arguments and
constructs VL53L5CX(sda=, scl=) from BOARD, then calls init()/start(). Covers:
happy path, no_device retry (DeviceNotFoundError from the constructor), init error
retry (OSError from the constructor), and ValueError/RuntimeError from init()
(e.g. a poll timeout during firmware loading).
"""

import ast
import os
import pathlib
from collections import namedtuple
from types import SimpleNamespace
from typing import Any, ClassVar

from vl53l5cx import DeviceNotFoundError

_FIRMWARE = pathlib.Path(__file__).parent.parent / "firmware" / "main.py"
_KEEP_FUNCS = {"emit", "stream", "init_sensor"}
Board = namedtuple("Board", ("name", "sda", "scl"))
_TEST_BOARD = Board(name="RP2040-Zero", sda=0, scl=1)


class _FakeTime:
    """Monotonic ticks_ms counter, ticks_diff, and no-op sleep_ms."""

    def __init__(self) -> None:
        self.ticks = 0

    def ticks_ms(self):
        self.ticks += 1
        return self.ticks

    def ticks_diff(self, a, b):
        return a - b

    def sleep_ms(self, _ms):
        return


class _FakeStatus:
    """Record every transition call by name into self.calls."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __getattr__(self, name) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)

        def _rec():
            self.calls.append(name)

        return _rec


class _FakeVL53L5CX:
    """VL53L5CX stand-in: pops `script` per construction, records init()/start()."""

    script: ClassVar[list] = []

    def __init__(self, *, sda, scl) -> None:
        if type(self).script:
            outcome = type(self).script.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
        self.addr = 0x29
        self._inited = False
        self._started = False
        self._freq = None

    def init(self) -> None:
        self._inited = True

    def start(self, freq=10) -> None:
        self._started = True
        self._freq = freq


def _make_init_ns():
    """Create AST-loaded namespace with _FakeVL53L5CX injected."""
    _FakeVL53L5CX.script = []
    fake_time = _FakeTime()
    fake_status = _FakeStatus()

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
        "os": os,
        "namedtuple": namedtuple,
        "BOARD": _TEST_BOARD,
        "VL53L5CX": _FakeVL53L5CX,
        "DeviceNotFoundError": DeviceNotFoundError,
    }
    exec(code, ns)
    return SimpleNamespace(ns=ns, time=fake_time, status=fake_status)


def test_init_sensor_happy_path():
    init_ns = _make_init_ns()
    tof = init_ns.ns["init_sensor"]()
    assert isinstance(tof, _FakeVL53L5CX)
    assert tof._inited is True
    assert tof._started is True
    assert init_ns.status.calls == ["i2c_init"]


def test_init_sensor_retries_when_device_missing():
    init_ns = _make_init_ns()
    _FakeVL53L5CX.script = [DeviceNotFoundError("no device"), None]
    init_ns.ns["init_sensor"]()
    assert init_ns.status.calls == ["i2c_init", "no_device"]


def test_init_sensor_retries_on_oserror():
    init_ns = _make_init_ns()
    _FakeVL53L5CX.script = [OSError("bus fault"), None]
    init_ns.ns["init_sensor"]()
    assert "init_err" in init_ns.status.calls


def test_init_sensor_retries_on_value_error():
    init_ns = _make_init_ns()
    call = {"n": 0}

    class _FailOnce(_FakeVL53L5CX):
        def init(self):
            call["n"] += 1
            if call["n"] == 1:
                raise ValueError("poll_for_answer failed")
            super().init()

    init_ns.ns["VL53L5CX"] = _FailOnce
    init_ns.ns["init_sensor"]()
    assert "init_err" in init_ns.status.calls


def test_init_sensor_retries_on_runtime_error():
    init_ns = _make_init_ns()
    call = {"n": 0}

    class _RTEOnce(_FakeVL53L5CX):
        def init(self):
            call["n"] += 1
            if call["n"] == 1:
                raise RuntimeError("driver timeout")
            super().init()

    init_ns.ns["VL53L5CX"] = _RTEOnce
    init_ns.ns["init_sensor"]()
    assert "init_err" in init_ns.status.calls
