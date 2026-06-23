"""Host CPython pytest tests for the QMC5883P driver against the register simulator.

Logic-only coverage: device scan, chip-ID validation, the init register
sequence, signed little-endian decode, the data-ready poll loop, and the OVL
status bit. The driver opens its own bus from flat pins, so the fake is
registered in the machine stub's device registry and the driver's internal
scan() finds it. Silicon quirks (NACK retries, clock-stretch timeouts) are out
of scope — those need hardware.
"""

import machine
import pytest
from fake_qmc5883p import FakeQMC5883P

from qmc5883p import QMC5883P, DeviceNotFoundError

ADDR = 0x2C


def _register_fake(**kwargs):
    """Reset machine state and register a FakeQMC5883P at 0x2C."""
    machine.reset()
    dev = FakeQMC5883P(**kwargs)
    machine.register_device(ADDR, dev)
    return dev


def test_chip_id_accepted():
    _register_fake()
    mag = QMC5883P(sda=0, scl=1)
    assert mag.address == ADDR


def test_missing_device_raises_device_not_found():
    """Nothing registered on the bus → DeviceNotFoundError, not OSError."""
    machine.reset()
    with pytest.raises(DeviceNotFoundError):
        QMC5883P(sda=0, scl=1)


def test_unknown_chip_id_raises():
    _register_fake(chip_id=0xAA)
    with pytest.raises(OSError):
        QMC5883P(sda=0, scl=1)


def test_init_writes_config_sequence():
    """soft-reset (CTRL_2) → AXIS_SIGN → range (CTRL_2) → CTRL_1, in order."""
    fake_mag = _register_fake()
    QMC5883P(sda=0, scl=1)
    assert fake_mag.writes == [
        (0x0B, bytes((0x80,))),  # CTRL_2 soft reset
        (0x29, bytes((0x06,))),  # AXIS_SIGN invert X/Y
        (0x0B, bytes((0b00 << 2,))),  # CTRL_2 ±2 G range (0x00)
        (0x0A, bytes(((0b01 << 2) | 0b01,))),  # CTRL_1 continuous/50 Hz/OSR=512 (0x05)
    ]


def test_read_returns_signed_xyz():
    """6-byte DATA block decodes as three signed little-endian shorts."""
    fake_mag = _register_fake()
    mag = QMC5883P(sda=0, scl=1)
    fake_mag.set_sample(100, -200, 300)
    assert mag.read() == (100, -200, 300)


def test_read_polls_until_drdy():
    """read() spins on STATUS DRDY before fetching DATA."""
    fake_mag = _register_fake()
    mag = QMC5883P(sda=0, scl=1)
    fake_mag.set_sample(1, 2, 3)
    fake_mag.drdy_after(2)  # not-ready twice, then ready
    assert mag.read() == (1, 2, 3)


def test_last_status_exposes_ovl():
    fake_mag = _register_fake()
    mag = QMC5883P(sda=0, scl=1)
    fake_mag.set_overflow(True)
    mag.read()
    assert mag.last_status & 0x02


def test_last_status_clear_without_ovl():
    _register_fake()
    mag = QMC5883P(sda=0, scl=1)
    mag.read()
    assert not (mag.last_status & 0x02)
