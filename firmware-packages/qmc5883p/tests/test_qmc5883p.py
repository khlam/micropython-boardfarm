"""Host CPython pytest tests for the QMC5883P driver against the register simulator.

Logic-only coverage: chip-ID validation, the init register sequence, signed
little-endian decode, the data-ready poll loop, and the OVL status bit. Silicon
quirks (NACK retries, clock-stretch timeouts) are out of scope — those need
hardware.
"""

import machine
import pytest
from fake_qmc5883p import FakeQMC5883P

from qmc5883p import QMC5883P

ADDR = 0x2C


def test_chip_id_accepted(fake_mag):
    mag = QMC5883P(_make_i2c())
    assert mag.address == ADDR


def test_unknown_chip_id_raises():
    machine.register_device(ADDR, FakeQMC5883P(chip_id=0xAA))
    with pytest.raises(OSError):
        QMC5883P(_make_i2c())


def test_init_writes_config_sequence(fake_mag):
    """soft-reset (CTRL_2) → AXIS_SIGN → range (CTRL_2) → CTRL_1, in order."""
    QMC5883P(_make_i2c())
    assert fake_mag.writes == [
        (0x0B, bytes((0x80,))),  # CTRL_2 soft reset
        (0x29, bytes((0x06,))),  # AXIS_SIGN invert X/Y
        (0x0B, bytes((0b00 << 2,))),  # CTRL_2 ±2 G range (0x00)
        (0x0A, bytes(((0b01 << 2) | 0b01,))),  # CTRL_1 continuous/50 Hz/OSR=512 (0x05)
    ]


def test_read_returns_signed_xyz(fake_mag):
    """6-byte DATA block decodes as three signed little-endian shorts."""
    mag = QMC5883P(_make_i2c())
    fake_mag.set_sample(100, -200, 300)
    assert mag.read() == (100, -200, 300)


def test_read_polls_until_drdy(fake_mag):
    """read() spins on STATUS DRDY before fetching DATA."""
    mag = QMC5883P(_make_i2c())
    fake_mag.set_sample(1, 2, 3)
    fake_mag.drdy_after(2)  # not-ready twice, then ready
    assert mag.read() == (1, 2, 3)


def test_last_status_exposes_ovl(fake_mag):
    mag = QMC5883P(_make_i2c())
    fake_mag.set_overflow(True)
    mag.read()
    assert mag.last_status & 0x02


def test_last_status_clear_without_ovl(fake_mag):
    mag = QMC5883P(_make_i2c())
    mag.read()
    assert not (mag.last_status & 0x02)


def _make_i2c():
    return machine.SoftI2C(sda=machine.Pin(0), scl=machine.Pin(1))
