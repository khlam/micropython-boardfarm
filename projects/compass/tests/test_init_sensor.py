"""Host CPython pytest tests for init_sensor in compass firmware.

The driver opens its own bus and scans, so init_sensor() takes no arguments and
constructs QMC5883P(bus_id=, sda=, scl=) from BOARD. A fake driver class drives the
happy path, the no_device retry (DeviceNotFoundError), and the init_err (OSError,
e.g. a chip-ID mismatch) retry.
"""

import math
import os
import pathlib
from collections import namedtuple
from typing import ClassVar

from micropython_stubs.testing import firmware_namespace
from qmc5883p import DeviceNotFoundError

_FIRMWARE = pathlib.Path(__file__).parent.parent / "firmware" / "main.py"
_KEEP_FUNCS = {"emit", "init_sensor", "stream"}
Board = namedtuple("Board", ("name", "i2c_id", "sda", "scl"))
_TEST_BOARD = Board(name="RP2040-Zero", i2c_id=0, sda=0, scl=1)
ADDR = 0x2C


class _FakeMag:
    """QMC5883P stand-in: pops `script` per construction to raise or succeed."""

    script: ClassVar[list] = []

    def __init__(self, *, sda, scl, bus_id=0, address=ADDR) -> None:
        if type(self).script:
            outcome = type(self).script.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
        self.address = address
        self.last_status = 0


def _make_init_ns():
    """Create AST-loaded namespace with _FakeMag injected."""
    _FakeMag.script = []
    from smoothing import simple_moving_average

    return firmware_namespace(
        _FIRMWARE,
        _KEEP_FUNCS,
        os=os,
        namedtuple=namedtuple,
        BOARD=_TEST_BOARD,
        math=math,
        simple_moving_average=simple_moving_average,
        QMC5883P=_FakeMag,
        DeviceNotFoundError=DeviceNotFoundError,
    )


def test_init_sensor_happy_path():
    init_ns = _make_init_ns()
    mag = init_ns.ns["init_sensor"]()
    assert mag.address == ADDR
    assert init_ns.status.calls == ["i2c_init"]


def test_init_sensor_retries_when_device_missing():
    init_ns = _make_init_ns()
    _FakeMag.script = [DeviceNotFoundError("no device"), None]
    init_ns.ns["init_sensor"]()
    assert init_ns.status.calls == ["i2c_init", "no_device"]


def test_init_sensor_handles_init_err():
    init_ns = _make_init_ns()
    _FakeMag.script = [OSError("scripted chip-ID fail"), None]
    init_ns.ns["init_sensor"]()
    assert "init_err" in init_ns.status.calls
