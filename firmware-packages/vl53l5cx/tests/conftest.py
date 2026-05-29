"""Host CPython pytest fixtures for the vl53l5cx package tests.

Provides a pre-wired VL53L5CX instance with a no-op I2C stub so that
driver internals (init(), start_ranging(), etc.) can be bypassed and the
public read() / check_data_ready() wrapper behaviour tested in isolation.
"""

import pytest

from vl53l5cx.vl53l5cx import VL53L5CX


class _FakeI2C:
    """No-op I2C stub: readfrom_mem returns zeros, writes are discarded."""

    def readfrom_mem_into(
        self, addr: int, reg: int, buf: bytearray, addrsize: int = 16
    ) -> None:
        """Fill buf with zeros."""
        for i in range(len(buf)):
            buf[i] = 0

    def readfrom_mem(self, addr: int, reg: int, size: int, addrsize: int = 16) -> bytes:
        """Return size zero bytes."""
        return bytes(size)

    def writeto_mem(self, addr: int, reg: int, buf: bytes, addrsize: int = 16) -> None:
        """Discard the write."""


@pytest.fixture
def tof() -> VL53L5CX:
    """VL53L5CX bound to a no-op I2C stub with _data_read_size pre-set.

    Does NOT call init() or start_ranging() — tests that exercise read()
    or check_data_ready() can call these methods without hardware present.
    """
    sensor = VL53L5CX(_FakeI2C())
    sensor._data_read_size = 32
    return sensor
