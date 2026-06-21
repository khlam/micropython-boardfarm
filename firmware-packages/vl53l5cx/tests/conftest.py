"""Host CPython pytest fixtures for the vl53l5cx package tests.

The driver opens its own soft I²C bus from flat pins and scans for the device at
construction, so a minimal fake is registered in the machine stub's device
registry at 0x29 to satisfy the scan. The fixture does NOT call init() or
start_ranging() — tests that exercise read() / check_data_ready() override the
transport methods they need, so the fake only has to make scan() succeed.
"""

import machine
import pytest

from vl53l5cx.vl53l5cx import VL53L5CX


class _FakeVL53L5CX:
    """No-op register responder: present on the bus, returns zeros."""

    def read(self, _reg: int, nbytes: int) -> bytes:
        """Return nbytes of zeros."""
        return bytes(nbytes)

    def write(self, _reg: int, _data: bytes) -> None:
        """Discard the write."""


@pytest.fixture(autouse=True)
def _reset_devices():
    """Clear the shared machine-stub device registry between tests."""
    machine.reset()
    yield


@pytest.fixture
def tof() -> VL53L5CX:
    """VL53L5CX bound to a registered fake at 0x29 with _data_read_size pre-set.

    Does NOT call init() or start_ranging() — tests that exercise read()
    or check_data_ready() can call these methods without hardware present.
    """
    machine.register_device(0x29, _FakeVL53L5CX())
    sensor = VL53L5CX(sda=0, scl=1)
    sensor._data_read_size = 32
    return sensor
