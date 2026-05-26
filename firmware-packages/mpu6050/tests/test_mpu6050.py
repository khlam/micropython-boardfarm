"""Host CPython pytest tests for the MPU6050 driver against the register simulator.

The simulator is faithful enough to exercise WHO_AM_I dispatch, LSB
conversion arithmetic, chip-specific temperature transfer, and the
saturation flag. Silicon quirks (NACK retries, clock-stretch timeouts)
are out of scope — those need hardware.
"""

import machine
import pytest
from fake_mpu6050 import FakeMPU6050

from mpu6050 import MPU6050


def test_who_am_i_dispatch_mpu6050(fake_imu):
    imu = MPU6050(_make_i2c(), addr=0x68)
    assert imu.kind == "MPU6050"


@pytest.mark.parametrize(
    "who, kind",
    [(0x70, "MPU6500"), (0x71, "MPU9250")],
)
def test_who_am_i_dispatch_variants(who, kind):
    dev = FakeMPU6050(who_am_i=who)
    machine.register_device(0x68, dev)
    imu = MPU6050(_make_i2c(), addr=0x68)
    assert imu.kind == kind


def test_unknown_who_am_i_raises():
    machine.register_device(0x68, FakeMPU6050(who_am_i=0xAA))
    with pytest.raises(OSError):
        MPU6050(_make_i2c(), addr=0x68)


def test_accel_gyro_lsb_conversion(fake_imu):
    """16384 LSB = 1 g; 131 LSB = 1 °/s — sanity check arithmetic."""
    imu = MPU6050(_make_i2c(), addr=0x68)
    fake_imu.set_sample(ax=16384, ay=-16384, az=0, gx=131, gy=-131, gz=0, temp_raw=0)
    ax, ay, az, gx, gy, gz, _ = imu.read_all()
    assert ax == pytest.approx(1.0)
    assert ay == pytest.approx(-1.0)
    assert az == pytest.approx(0.0)
    assert gx == pytest.approx(1.0)
    assert gy == pytest.approx(-1.0)
    assert gz == pytest.approx(0.0)


def test_temperature_transfer_mpu6050(fake_imu):
    """MPU6050: T = raw / 340 + 36.53."""
    imu = MPU6050(_make_i2c(), addr=0x68)
    fake_imu.set_sample(0, 0, 0, 0, 0, 0, temp_raw=0)
    _, _, _, _, _, _, t = imu.read_all()
    assert t == pytest.approx(36.53, abs=1e-2)


def test_temperature_transfer_mpu6500():
    """MPU6500/MPU9250: T = raw / 333.87 + 21.0."""
    dev = FakeMPU6050(who_am_i=0x70)
    machine.register_device(0x68, dev)
    imu = MPU6050(_make_i2c(), addr=0x68)
    dev.set_sample(0, 0, 0, 0, 0, 0, temp_raw=0)
    _, _, _, _, _, _, t = imu.read_all()
    assert t == pytest.approx(21.0, abs=1e-2)


def test_saturation_flag_clear(fake_imu):
    imu = MPU6050(_make_i2c(), addr=0x68)
    fake_imu.set_sample(0, 0, 0, 0, 0, 0, 0)
    imu.read_all()
    assert imu.last_saturated is False


@pytest.mark.parametrize(
    "axis_kwargs",
    [
        {"ax": 32767},
        {"ay": -32768},
        {"az": 32767},
        {"gx": -32768},
        {"gy": 32767},
        {"gz": -32768},
    ],
)
def test_saturation_flag_set_on_int16_rail(fake_imu, axis_kwargs):
    imu = MPU6050(_make_i2c(), addr=0x68)
    sample = {"ax": 0, "ay": 0, "az": 0, "gx": 0, "gy": 0, "gz": 0, "temp_raw": 0}
    sample.update(axis_kwargs)
    fake_imu.set_sample(**sample)
    imu.read_all()
    assert imu.last_saturated is True


def _make_i2c():
    return machine.SoftI2C(sda=machine.Pin(0), scl=machine.Pin(1))
