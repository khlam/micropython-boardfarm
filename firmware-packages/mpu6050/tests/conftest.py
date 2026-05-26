"""Host CPython pytest fixtures for mpu6050."""

import machine
import pytest
from fake_mpu6050 import FakeMPU6050


@pytest.fixture(autouse=True)
def _reset_devices():
    """Clear the shared machine-stub device registry between tests."""
    machine.reset()
    yield


@pytest.fixture
def fake_imu():
    """Default fake at 0x68 (MPU6050)."""
    dev = FakeMPU6050(who_am_i=0x68)
    machine.register_device(0x68, dev)
    return dev
