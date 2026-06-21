"""MCU-micropython driver for the VL53L0X time-of-flight sensor.

The driver takes flat pin numbers, opens its own bit-banged soft I²C bus,
scans, and soft-resets the chip. ``DeviceNotFoundError`` is re-exported so a project
imports its retry-loop exception from here, never from ``i2c_bus``.
"""

from i2c_bus import DeviceNotFoundError
from vl53l0x.vl53l0x import VL53L0X

__all__ = ["VL53L0X", "DeviceNotFoundError"]
