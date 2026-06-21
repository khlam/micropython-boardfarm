"""Host CPython pytest tests for init_sensor in distance-stream firmware.

The driver opens its own bus, scans, and soft-resets the chip, so init_sensor()
takes no arguments and constructs VL53L0X(sda=, scl=) from BOARD. A fake driver
class drives the happy path, the no_device retry (DeviceNotFoundError), the init_err
(OSError) retry, and the RuntimeError (driver poll timeout) retry. The soft-reset
handshake now lives in the driver and is covered by the vl53l0x package tests.
"""

from typing import ClassVar

import pytest

from vl53l0x import DeviceNotFoundError

TOF_ADDRESS = 0x29


def test_init_sensor_happy_path(init_ns):
    tof = init_ns.ns["init_sensor"]()
    assert isinstance(tof, _FakeVL53L0X)
    assert tof._budget == 20_000  # TIMING_BUDGET_US
    assert tof._started is True
    assert init_ns.status.calls == ["i2c_init"]


def test_init_sensor_retries_when_device_missing(init_ns):
    _FakeVL53L0X.script = [DeviceNotFoundError("no device"), None]
    init_ns.ns["init_sensor"]()
    assert init_ns.status.calls == ["i2c_init", "no_device"]


def test_init_sensor_handles_init_err(init_ns):
    _FakeVL53L0X.script = [OSError("first attempt fails"), None]
    init_ns.ns["init_sensor"]()
    assert "init_err" in init_ns.status.calls


def test_init_sensor_handles_runtime_error_during_init(init_ns):
    # RuntimeError (driver poll timeout) is also caught and routed to init_err.
    _FakeVL53L0X.script = [RuntimeError("driver poll timeout"), None]
    init_ns.ns["init_sensor"]()
    assert "init_err" in init_ns.status.calls


@pytest.fixture(autouse=True)
def _reset_tof():
    _FakeVL53L0X.script = []
    yield


@pytest.fixture
def init_ns(main_ns):
    """Inject the fake VL53L0X class into the main.py namespace."""
    main_ns.ns["VL53L0X"] = _FakeVL53L0X
    return main_ns


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
