"""Host CPython pytest fixtures for qmc5883p."""

import machine
import pytest
from fake_qmc5883p import FakeQMC5883P


@pytest.fixture(autouse=True)
def _reset_devices():
    """Clear the shared machine-stub device registry between tests."""
    machine.reset()
    yield


@pytest.fixture
def fake_mag():
    """Default fake QMC5883P at 0x2C (valid chip-ID)."""
    dev = FakeQMC5883P()
    machine.register_device(0x2C, dev)
    return dev
