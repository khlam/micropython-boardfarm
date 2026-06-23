"""Host CPython pytest tests for the MPU6050 driver against the register simulator.

The simulator is faithful enough to exercise address auto-detection, WHO_AM_I
dispatch, LSB conversion arithmetic, chip-specific temperature transfer, and the
saturation flag. The driver opens its own bus from flat pins, so the fake is
registered in the machine stub's device registry and the driver's internal
scan() finds it. Silicon quirks (NACK retries, clock-stretch timeouts) are out
of scope — those need hardware.
"""

import machine
import pytest
from fake_mpu6050 import FakeMPU6050

from mpu6050 import MPU6050, DeviceNotFoundError


def _register_fake(addr=0x68, **kwargs):
    """Reset machine state and register a FakeMPU6050 at addr."""
    machine.reset()
    dev = FakeMPU6050(**kwargs)
    machine.register_device(addr, dev)
    return dev


def test_who_am_i_dispatch_mpu6050():
    _register_fake(who_am_i=0x68)
    imu = MPU6050(sda=0, scl=1)
    assert imu.kind == "MPU6050"
    assert imu.addr == 0x68


def test_missing_device_raises_device_not_found():
    """Nothing registered on the bus → DeviceNotFoundError, not OSError."""
    machine.reset()
    with pytest.raises(DeviceNotFoundError):
        MPU6050(sda=0, scl=1)


def test_secondary_address_auto_detected():
    """AD0=3V3 puts the device at 0x69; the driver finds it without help."""
    _register_fake(addr=0x69, who_am_i=0x68)
    imu = MPU6050(sda=0, scl=1)
    assert imu.addr == 0x69


@pytest.mark.parametrize(
    "who, kind",
    [(0x70, "MPU6500"), (0x71, "MPU9250")],
)
def test_who_am_i_dispatch_variants(who, kind):
    _register_fake(who_am_i=who)
    imu = MPU6050(sda=0, scl=1)
    assert imu.kind == kind


def test_unknown_who_am_i_raises():
    _register_fake(who_am_i=0xAA)
    with pytest.raises(OSError):
        MPU6050(sda=0, scl=1)


def test_accel_gyro_lsb_conversion():
    """16384 LSB = 1 g; 131 LSB = 1 °/s — sanity check arithmetic."""
    fake_imu = _register_fake(who_am_i=0x68)
    imu = MPU6050(sda=0, scl=1)
    fake_imu.set_sample(ax=16384, ay=-16384, az=0, gx=131, gy=-131, gz=0, temp_raw=0)
    ax, ay, az, gx, gy, gz, _ = imu.read_all()
    assert ax == pytest.approx(1.0)
    assert ay == pytest.approx(-1.0)
    assert az == pytest.approx(0.0)
    assert gx == pytest.approx(1.0)
    assert gy == pytest.approx(-1.0)
    assert gz == pytest.approx(0.0)


def test_temperature_transfer_mpu6050():
    """MPU6050: T = raw / 340 + 36.53."""
    fake_imu = _register_fake(who_am_i=0x68)
    imu = MPU6050(sda=0, scl=1)
    fake_imu.set_sample(0, 0, 0, 0, 0, 0, temp_raw=0)
    _, _, _, _, _, _, t = imu.read_all()
    assert t == pytest.approx(36.53, abs=1e-2)


def test_temperature_transfer_mpu6500():
    """MPU6500/MPU9250: T = raw / 333.87 + 21.0."""
    dev = _register_fake(who_am_i=0x70)
    imu = MPU6050(sda=0, scl=1)
    dev.set_sample(0, 0, 0, 0, 0, 0, temp_raw=0)
    _, _, _, _, _, _, t = imu.read_all()
    assert t == pytest.approx(21.0, abs=1e-2)


def test_saturation_flag_clear():
    fake_imu = _register_fake(who_am_i=0x68)
    imu = MPU6050(sda=0, scl=1)
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
def test_saturation_flag_set_on_int16_rail(axis_kwargs):
    fake_imu = _register_fake(who_am_i=0x68)
    imu = MPU6050(sda=0, scl=1)
    sample = {"ax": 0, "ay": 0, "az": 0, "gx": 0, "gy": 0, "gz": 0, "temp_raw": 0}
    sample.update(axis_kwargs)
    fake_imu.set_sample(**sample)
    imu.read_all()
    assert imu.last_saturated is True
