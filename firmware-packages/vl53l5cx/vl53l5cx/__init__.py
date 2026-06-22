"""MCU-micropython driver for the VL53L5CX 8x8 multizone time-of-flight sensor.

Thin wrapper around the vendored ``vl53l5cx.vl53l5cx`` register driver. The
vendored file accepts a pre-built ``i2c`` object; this module adds
project-specific concerns — bus creation, device scan, LPN pin setup — so
that firmware only passes flat pin numbers.

``DeviceNotFoundError`` is re-exported so a project imports its retry-loop
exception from here, never from ``i2c_bus``.
"""

from i2c_bus import DeviceNotFoundError, soft_i2c
from vl53l5cx.vl53l5cx import VL53L5CX as _VendorVL53L5CX  # noqa: N811


class VL53L5CX(_VendorVL53L5CX):
    """VL53L5CX with bus management and device scan.

    The vendored base class takes a ready-made ``i2c`` object and an optional
    ``machine.Pin`` for LPN. This subclass creates a soft I²C bus from flat
    pin numbers, confirms the chip is present, wraps LPN as a Pin, then
    delegates to the vendor ``__init__``.
    """

    def __init__(self, *, sda: int, scl: int, address: int = 0x29, lpn: int | None = None) -> None:
        """Create a VL53L5CX driver from flat pin numbers.

        Args:
            sda: GPIO number for the I²C data line.
            scl: GPIO number for the I²C clock line.
            address: 7-bit I²C address; default 0x29.
            lpn: Optional GPIO number for the LPN (enable) line. Pass a pin
                pulled high to enable hardware reset via reset(). None means
                the pin is not controlled (safe if the board pulls LPN high).

        Raises:
            DeviceNotFoundError: Nothing ACKed at ``address`` on the scanned bus.
        """
        i2c = soft_i2c(sda, scl)
        if address not in i2c.scan():
            raise DeviceNotFoundError(f"VL53L5CX not found at 0x{address:02x}")
        super().__init__(i2c, address, _init_lpn(lpn))


def _init_lpn(lpn: int | None) -> object:
    """Wrap an optional LPN GPIO number in an output Pin, or return None."""
    if lpn is None:
        return None
    from machine import Pin  # noqa: PLC0415

    return Pin(lpn, Pin.OUT)


__all__ = ["VL53L5CX", "DeviceNotFoundError"]
