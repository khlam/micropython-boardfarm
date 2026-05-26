"""MCU-micropython backend for the ESP32-S3 I²C bus (GPIO1=SDA, GPIO2=SCL, soft + hardware)."""

from machine import I2C, Pin, SoftI2C


def __getattr__(name: str) -> object:
    """Lazily instantiate the requested bus so the other is never created.

    Both buses share GPIO1/GPIO2. See rp2040.py for the pin-conflict rationale.

    Args:
        name: ``soft_i2c`` or ``hard_i2c``.

    Returns:
        A SoftI2C or I2C instance on GPIO1/GPIO2.

    Raises:
        AttributeError: When name is not ``soft_i2c`` or ``hard_i2c``.
    """
    if name == "soft_i2c":
        # SoftI2C: hw I²C NACKs on register 0x83 during VL53L0X SPAD-info
        # because the sensor clock-stretches across that operation and hw I²C
        # loses sync.
        v = SoftI2C(sda=Pin(1), scl=Pin(2), freq=100_000)
    elif name == "hard_i2c":
        v = I2C(0, sda=Pin(1), scl=Pin(2), freq=400_000)
    else:
        raise AttributeError(name)
    globals()[name] = v
    return v
