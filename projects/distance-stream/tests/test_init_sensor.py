"""Host CPython pytest tests for init_sensor in distance-stream firmware.

The driver opens its own bus, scans, and soft-resets the chip, so init_sensor()
takes no arguments and constructs VL53L0X(sda=, scl=) from BOARD. A fake driver
class drives the happy path, the no_device retry (DeviceNotFoundError), the init_err
(OSError) retry, and the RuntimeError (driver poll timeout) retry. The soft-reset
handshake now lives in the driver and is covered by the vl53l0x package tests.
"""

import ast
import os
import pathlib
from collections import namedtuple
from types import SimpleNamespace
from typing import Any, ClassVar

from vl53l0x import DeviceNotFoundError

_FIRMWARE = pathlib.Path(__file__).parent.parent / "firmware" / "main.py"
_KEEP_FUNCS = {"emit", "stream", "init_sensor"}
Board = namedtuple("Board", ("name", "sda", "scl"))
_TEST_BOARD = Board(name="RP2040-Zero", sda=0, scl=1)
TOF_ADDRESS = 0x29


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


class _FakeVL53L0X:
    """VL53L0X stand-in: pops `script` per construction, records budget + start."""

    script: ClassVar[list] = []

    def __init__(self, *, sda, scl) -> None:
        if type(self).script:
            outcome = type(self).script.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
        self.address = TOF_ADDRESS
        self._budget = None
        self._started = False

    def set_measurement_timing_budget(self, budget):
        self._budget = budget

    def start(self):
        self._started = True


def _make_init_ns():
    """Create AST-loaded namespace with _FakeVL53L0X injected."""
    _FakeVL53L0X.script = []
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

    from smoothing import median

    ns: dict = {
        "time": fake_time,
        "status": fake_status,
        "ujson": ujson,
        "os": os,
        "namedtuple": namedtuple,
        "BOARD": _TEST_BOARD,
        "median": median,
        "VL53L0X": _FakeVL53L0X,
        "DeviceNotFoundError": DeviceNotFoundError,
    }
    exec(code, ns)
    return SimpleNamespace(ns=ns, time=fake_time, status=fake_status)


def test_init_sensor_happy_path():
    init_ns = _make_init_ns()
    tof = init_ns.ns["init_sensor"]()
    assert isinstance(tof, _FakeVL53L0X)
    assert tof._budget == 20_000  # TIMING_BUDGET_US
    assert tof._started is True
    assert init_ns.status.calls == ["i2c_init"]


def test_init_sensor_retries_when_device_missing():
    init_ns = _make_init_ns()
    _FakeVL53L0X.script = [DeviceNotFoundError("no device"), None]
    init_ns.ns["init_sensor"]()
    assert init_ns.status.calls == ["i2c_init", "no_device"]


def test_init_sensor_handles_init_err():
    init_ns = _make_init_ns()
    _FakeVL53L0X.script = [OSError("first attempt fails"), None]
    init_ns.ns["init_sensor"]()
    assert "init_err" in init_ns.status.calls


def test_init_sensor_handles_runtime_error_during_init():
    init_ns = _make_init_ns()
    _FakeVL53L0X.script = [RuntimeError("driver poll timeout"), None]
    init_ns.ns["init_sensor"]()
    assert "init_err" in init_ns.status.calls
