"""MCU-micropython QMC5883P magnetometer driver.

The driver takes flat pin numbers and opens its own hardware I²C bus, so the
project's BOARD table supplies only pins. ``DeviceNotFoundError`` is re-exported so a
project imports its retry-loop exception from here, never from ``i2c_bus``.
"""

from i2c_bus import DeviceNotFoundError
from qmc5883p.qmc5883p import QMC5883P

__all__ = ["QMC5883P", "DeviceNotFoundError"]
