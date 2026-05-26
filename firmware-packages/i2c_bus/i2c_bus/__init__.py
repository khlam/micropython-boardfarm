"""MCU-micropython package selecting the correct I²C chip backend at import time.

Example:
    from i2c_bus import soft_i2c   # sensors that clock-stretch (VL53L0X)
    from i2c_bus import hard_i2c   # sensors that don't (MPU6050)
"""

import os

import i2c_bus.esp32s3
import i2c_bus.rp2040
import i2c_bus.rp2350

_machine = os.uname().machine
if "ESP32S3" in _machine:
    _backend = i2c_bus.esp32s3
elif "RP2350" in _machine:
    _backend = i2c_bus.rp2350
else:
    _backend = i2c_bus.rp2040


def __getattr__(name: str) -> object:
    """Lazily forward bus lookups to the chip-specific backend.

    Only the requested bus is instantiated — importing soft_i2c never
    creates hard_i2c, so the two I²C peripherals cannot conflict on shared
    pins even though both backends define both names.

    Args:
        name: Attribute name; must be ``soft_i2c`` or ``hard_i2c``.

    Returns:
        The constructed I²C bus instance for the running chip.

    Raises:
        AttributeError: When name is not a known bus export.
    """
    if name not in ("soft_i2c", "hard_i2c"):
        raise AttributeError(name)
    v = getattr(_backend, name)
    globals()[name] = v  # cache so subsequent accesses bypass __getattr__
    return v


__all__ = ["hard_i2c", "soft_i2c"]
