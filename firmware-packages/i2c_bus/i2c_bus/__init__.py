"""MCU-micropython internal I²C bus helpers, consumed only by sensor drivers.

A driver supplies the plain pin numbers from the project's ``BOARD`` table and
gets back a ready ``machine.I2C`` / ``SoftI2C``; the project never sees this
package. Nothing here touches ``os.uname()`` or claims a pin at import time.

Example (inside a driver):
    from i2c_bus import DeviceNotFoundError, hard_i2c
    i2c = hard_i2c(bus_id=0, sda=0, scl=1)     # sensors that don't clock-stretch
    if address not in i2c.scan():
        raise DeviceNotFoundError(...)
"""

__all__ = ["DeviceNotFoundError", "hard_i2c", "soft_i2c"]


class DeviceNotFoundError(Exception):
    """No expected device ACKed on the opened I²C bus.

    Drivers raise this (instead of a generic ``OSError``) after scanning so a
    project's retry loop can tell "nothing on the bus" — bad wiring, power, or
    pull-ups — apart from "device present but init failed".
    """


def soft_i2c(sda: int, scl: int, freq: int = 100_000) -> object:
    """Build a bit-banged SoftI2C on the wired pins.

    Soft I²C tolerates the heavy clock-stretching some sensors do during
    bring-up (the VL53L0X/VL53L5CX firmware upload), which the hardware
    peripheral aborts on.

    Args:
        sda: GPIO number for the data line.
        scl: GPIO number for the clock line.
        freq: Bus clock in Hz; 100 kHz keeps long clock-stretches stable.

    Returns:
        A ready ``machine.SoftI2C``.
    """
    from machine import Pin, SoftI2C  # noqa: PLC0415

    return SoftI2C(sda=Pin(sda), scl=Pin(scl), freq=freq)


def hard_i2c(bus_id: int, sda: int, scl: int, freq: int = 400_000) -> object:
    """Build a hardware I2C peripheral on the wired pins.

    Args:
        bus_id: Selects the hardware I²C peripheral.
        sda: GPIO number for the data line.
        scl: GPIO number for the clock line.
        freq: Bus clock in Hz; 400 kHz for sensors that don't clock-stretch.

    Returns:
        A ready ``machine.I2C``.
    """
    from machine import I2C, Pin  # noqa: PLC0415

    return I2C(bus_id, sda=Pin(sda), scl=Pin(scl), freq=freq)
