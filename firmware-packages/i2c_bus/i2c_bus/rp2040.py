"""MCU-micropython backend for the RP2040 I²C bus (GP0=SDA, GP1=SCL, soft + hardware)."""

from machine import I2C, Pin, SoftI2C


def __getattr__(name: str) -> object:
    """Lazily instantiate the requested bus so the other is never created.

    Both buses share GP0/GP1. Instantiating I2C(0, ...) configures the pad
    multiplexer for the hardware peripheral, which prevents SoftI2C from
    bit-banging those pins. Lazy creation ensures only the imported bus
    touches the hardware.

    Args:
        name: ``soft_i2c`` or ``hard_i2c``.

    Returns:
        A SoftI2C or I2C instance on GP0/GP1.

    Raises:
        AttributeError: When name is not ``soft_i2c`` or ``hard_i2c``.
    """
    if name == "soft_i2c":
        # SoftI2C tolerates VL53L0X clock-stretching — the hardware peripheral
        # aborts stretched transactions and range reads silently return 0.
        v = SoftI2C(sda=Pin(0), scl=Pin(1), freq=100_000)
    elif name == "hard_i2c":
        # Hardware I2C0 on the same pins — use for sensors that don't
        # clock-stretch (e.g. MPU6050).
        v = I2C(0, sda=Pin(0), scl=Pin(1), freq=400_000)
    else:
        raise AttributeError(name)
    globals()[name] = v  # cache so subsequent accesses bypass __getattr__
    return v
