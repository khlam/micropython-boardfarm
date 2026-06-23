"""MCU-micropython driver for the MPU6050 / MPU6500 / MPU9250 IMU family.

The driver takes flat pin numbers, opens its own hardware I²C bus, and
auto-detects the device address. ``DeviceNotFoundError`` is re-exported so a project
imports its retry-loop exception from here, never from ``i2c_bus``.
"""

from i2c_bus import DeviceNotFoundError
from mpu6050.mpu6050 import MPU6050

__all__ = ["MPU6050", "DeviceNotFoundError"]
