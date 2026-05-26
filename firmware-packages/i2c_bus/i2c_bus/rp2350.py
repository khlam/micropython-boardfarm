"""MCU-micropython backend for the RP2350 I²C bus (GP0=SDA, GP1=SCL — same wiring as RP2040)."""

from machine import I2C, Pin, SoftI2C


def __getattr__(name: str) -> object:
    """Lazily instantiate the requested bus so the other is never created.

    Both buses share GP0/GP1. See rp2040.py for the pin-conflict rationale.

    Args:
        name: ``soft_i2c`` or ``hard_i2c``.

    Returns:
        A SoftI2C or I2C instance on GP0/GP1.

    Raises:
        AttributeError: When name is not ``soft_i2c`` or ``hard_i2c``.
    """
    if name == "soft_i2c":
        # SoftI2C: same clock-stretch rationale as rp2040.py.
        v = SoftI2C(sda=Pin(0), scl=Pin(1), freq=100_000)
    elif name == "hard_i2c":
        v = I2C(0, sda=Pin(0), scl=Pin(1), freq=400_000)
    else:
        raise AttributeError(name)
    globals()[name] = v
    return v
