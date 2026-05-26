"""Host CPython pytest fixtures for vl53l0x."""

import machine
import pytest
from fake_vl53l0x import FakeVL53L0X


@pytest.fixture(autouse=True)
def _reset_devices():
    """Clear the shared machine-stub device registry between tests."""
    machine.reset()
    yield


@pytest.fixture
def fake_tof():
    """Default fake ToF sensor at 0x29."""
    dev = FakeVL53L0X()
    machine.register_device(0x29, dev)
    return dev
