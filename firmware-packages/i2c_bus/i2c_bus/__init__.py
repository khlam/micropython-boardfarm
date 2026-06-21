"""MCU-micropython I²C bus factories built from a caller-supplied pin record.

The package owns *what* pins it needs — the ``Wiring`` schema — but not *which*:
the project's ``BOARD`` table fills ``Wiring`` per chip and passes it in. Nothing
here touches ``os.uname()`` or claims a pin at import time.

Example:
    from i2c_bus import Wiring, hard_i2c, soft_i2c
    bus = hard_i2c(Wiring(id=0, sda=0, scl=1))   # sensors that don't clock-stretch
    bus = soft_i2c(Wiring(id=0, sda=0, scl=1))   # sensors that do (VL53L0X/L5CX)
"""

from collections import namedtuple

__all__ = ["Wiring", "hard_i2c", "soft_i2c"]

# Pin schema for an I²C bus. ``id`` selects the hardware peripheral for
# hard_i2c; soft_i2c is bit-banged and ignores it.
Wiring = namedtuple("Wiring", ("id", "sda", "scl"))


def soft_i2c(wiring: Wiring, freq: int = 100_000) -> object:
    """Build a bit-banged SoftI2C on the wired pins.

    Soft I²C tolerates the heavy clock-stretching some sensors do during
    bring-up (the VL53L0X/VL53L5CX firmware upload), which the hardware
    peripheral aborts on.

    Args:
        wiring: A ``Wiring`` record; only ``sda``/``scl`` are used.
        freq: Bus clock in Hz; 100 kHz keeps long clock-stretches stable.

    Returns:
        A ready ``machine.SoftI2C``.
    """
    from machine import Pin, SoftI2C  # noqa: PLC0415

    return SoftI2C(sda=Pin(wiring.sda), scl=Pin(wiring.scl), freq=freq)


def hard_i2c(wiring: Wiring, freq: int = 400_000) -> object:
    """Build a hardware I2C peripheral on the wired pins.

    Args:
        wiring: A ``Wiring`` record; ``id`` selects the I²C peripheral.
        freq: Bus clock in Hz; 400 kHz for sensors that don't clock-stretch.

    Returns:
        A ready ``machine.I2C``.
    """
    from machine import I2C, Pin  # noqa: PLC0415

    return I2C(wiring.id, sda=Pin(wiring.sda), scl=Pin(wiring.scl), freq=freq)
