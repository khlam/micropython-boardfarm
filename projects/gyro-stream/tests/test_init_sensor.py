"""Host CPython pytest tests for init_sensor in gyro-stream firmware.

The driver opens its own bus and auto-detects the address, so init_sensor()
takes no arguments and constructs MPU6050(bus_id=, sda=, scl=) from BOARD. A fake
driver class drives the happy path, the no_device retry (DeviceNotFoundError), and
the init_err (OSError) retry. The 0x68/0x69 address probe now lives in the
driver, so it is covered by the mpu6050 package tests, not here.
"""

import os
import pathlib
from collections import namedtuple
from typing import ClassVar

from micropython_stubs.testing import firmware_namespace
from mpu6050 import DeviceNotFoundError

_FIRMWARE = pathlib.Path(__file__).parent.parent / "firmware" / "main.py"
_KEEP_FUNCS = {"emit", "init_sensor", "stream"}
Board = namedtuple("Board", ("name", "i2c_id", "sda", "scl"))
_TEST_BOARD = Board(name="RP2040-Zero", i2c_id=0, sda=0, scl=1)
PRIMARY = 0x68


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
    return firmware_namespace(
        _FIRMWARE,
        _KEEP_FUNCS,
        os=os,
        namedtuple=namedtuple,
        BOARD=_TEST_BOARD,
        MPU6050=_FakeIMU,
        DeviceNotFoundError=DeviceNotFoundError,
    )


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
