"""Host CPython pytest tests for init_sensor in gyro-stream firmware.

The driver opens its own bus and auto-detects the address, so init_sensor()
takes no arguments and constructs MPU6050(bus_id=, sda=, scl=) from BOARD. A fake
driver class drives the happy path, the no_device retry (DeviceNotFoundError), and
the init_err (OSError) retry. The 0x68/0x69 address probe now lives in the
driver, so it is covered by the mpu6050 package tests, not here.
"""

import ast
import os
import pathlib
from collections import namedtuple
from types import SimpleNamespace
from typing import Any, ClassVar

from mpu6050 import DeviceNotFoundError

_FIRMWARE = pathlib.Path(__file__).parent.parent / "firmware" / "main.py"
_KEEP_FUNCS = {"emit", "init_sensor", "stream"}
Board = namedtuple("Board", ("name", "i2c_id", "sda", "scl"))
_TEST_BOARD = Board(name="RP2040-Zero", i2c_id=0, sda=0, scl=1)
PRIMARY = 0x68


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


class _FakeIMU:
    """MPU6050 stand-in: pops `script` per construction to raise or succeed."""

    script: ClassVar[list] = []

    def __init__(self, *, sda, scl, bus_id=0) -> None:
        if type(self).script:
            outcome = type(self).script.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
        self.addr = PRIMARY
        self.kind = "MPU6050"
        self.last_saturated = False


def _make_init_ns():
    """Create AST-loaded namespace with _FakeIMU injected."""
    _FakeIMU.script = []
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
        "MPU6050": _FakeIMU,
        "DeviceNotFoundError": DeviceNotFoundError,
    }
    exec(code, ns)
    return SimpleNamespace(ns=ns, time=fake_time, status=fake_status)


def test_init_sensor_happy_path():
    init_ns = _make_init_ns()
    imu = init_ns.ns["init_sensor"]()
    assert imu.addr == PRIMARY
    assert init_ns.status.calls == ["i2c_init"]


def test_init_sensor_retries_when_device_missing():
    init_ns = _make_init_ns()
    _FakeIMU.script = [DeviceNotFoundError("no device"), None]
    init_ns.ns["init_sensor"]()
    assert init_ns.status.calls == ["i2c_init", "no_device"]


def test_init_sensor_handles_init_err():
    init_ns = _make_init_ns()
    _FakeIMU.script = [OSError("scripted WHO_AM_I fail"), None]
    init_ns.ns["init_sensor"]()
    assert "init_err" in init_ns.status.calls
