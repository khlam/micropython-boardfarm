"""MCU-micropython driver for the VL53L5CX 8x8 multizone time-of-flight sensor.

The driver takes flat pin numbers, opens its own bit-banged soft I²C bus, and
scans for the device. ``DeviceNotFoundError`` is re-exported so a project imports its
retry-loop exception from here, never from ``i2c_bus``.
"""

from i2c_bus import DeviceNotFoundError
from vl53l5cx.vl53l5cx import VL53L5CX

__all__ = ["VL53L5CX", "DeviceNotFoundError"]
