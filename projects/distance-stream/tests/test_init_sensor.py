"""Host CPython pytest tests for init_sensor in distance-stream firmware.

The driver opens its own bus, scans, and soft-resets the chip, so init_sensor()
takes no arguments and constructs VL53L0X(sda=, scl=) from BOARD. A fake driver
class drives the happy path, the no_device retry (DeviceNotFoundError), the init_err
(OSError) retry, and the RuntimeError (driver poll timeout) retry. The soft-reset
handshake now lives in the driver and is covered by the vl53l0x package tests.
"""

import os
import pathlib
from collections import namedtuple
from typing import ClassVar

from micropython_stubs.testing import ScriptedFake, firmware_namespace
from vl53l0x import DeviceNotFoundError

_FIRMWARE = pathlib.Path(__file__).parent.parent / "firmware" / "main.py"
_KEEP_FUNCS = {"emit", "stream", "init_sensor"}
Board = namedtuple("Board", ("name", "sda", "scl"))
_TEST_BOARD = Board(name="RP2040-Zero", sda=0, scl=1)
TOF_ADDRESS = 0x29


class _FakeVL53L0X(ScriptedFake):
    """VL53L0X stand-in (see ScriptedFake): records budget + start on success."""

    script: ClassVar[list] = []

    def __init__(self, *, sda, scl) -> None:
        super().__init__()
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
    from smoothing import median

    return firmware_namespace(
        _FIRMWARE,
        _KEEP_FUNCS,
        os=os,
        namedtuple=namedtuple,
        BOARD=_TEST_BOARD,
        median=median,
        VL53L0X=_FakeVL53L0X,
        DeviceNotFoundError=DeviceNotFoundError,
    )


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
