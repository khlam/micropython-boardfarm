"""Host CPython pytest tests for init_sensor in gyro-stream firmware.

The driver opens its own bus and auto-detects the address, so init_sensor()
takes no arguments and constructs MPU6050(bus_id=, sda=, scl=) from BOARD. A fake
driver class drives the happy path, the no_device retry (DeviceNotFoundError), and
the init_err (OSError) retry. The 0x68/0x69 address probe now lives in the
driver, so it is covered by the mpu6050 package tests, not here.
"""

from typing import ClassVar

import pytest

from mpu6050 import DeviceNotFoundError

PRIMARY = 0x68


def test_init_sensor_happy_path(init_ns):
    imu = init_ns.ns["init_sensor"]()
    assert imu.addr == PRIMARY
    assert init_ns.status.calls == ["i2c_init"]


def test_init_sensor_retries_when_device_missing(init_ns):
    _FakeIMU.script = [DeviceNotFoundError("no device"), None]
    init_ns.ns["init_sensor"]()
    assert init_ns.status.calls == ["i2c_init", "no_device"]


def test_init_sensor_handles_init_err(init_ns):
    _FakeIMU.script = [OSError("scripted WHO_AM_I fail"), None]
    init_ns.ns["init_sensor"]()
    assert "init_err" in init_ns.status.calls


@pytest.fixture(autouse=True)
def _reset_imu():
    _FakeIMU.script = []
    yield


@pytest.fixture
def init_ns(main_ns):
    main_ns.ns["MPU6050"] = _FakeIMU
    return main_ns


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
