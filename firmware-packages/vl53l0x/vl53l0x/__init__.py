"""MCU-micropython driver for the VL53L0X time-of-flight sensor.

Thin wrapper around the vendored ``vl53l0x.vl53l0x`` register driver. The
vendored file accepts a pre-built ``i2c`` object; this module adds
project-specific concerns — bus creation, device scan, soft-reset, and
default overrides — so that firmware only passes flat pin numbers.

``DeviceNotFoundError`` is re-exported so a project imports its retry-loop
exception from here, never from ``i2c_bus``.
"""

import utime

from i2c_bus import DeviceNotFoundError, soft_i2c
from vl53l0x.vl53l0x import IDENTIFICATION_MODEL_ID, SOFT_RESET_GO2_SOFT_RESET_N
from vl53l0x.vl53l0x import VL53L0X as _VendorVL53L0X  # noqa: N811

_SOFT_RESET_PAUSE_MS = 2
_SOFT_RESET_POLLS = 50
_MODEL_ID_BOOTED = 0xEE


class VL53L0X(_VendorVL53L0X):
    """VL53L0X with bus management, device scan, and soft-reset.

    The vendored base class takes a ready-made ``i2c`` object with upstream
    defaults (``skip_spad_info=False``, ``interrupt_status_mask=0x07``).
    This subclass creates a soft I²C bus from flat pin numbers, confirms
    the chip is present, soft-resets it, then delegates to the vendor
    ``__init__`` with project defaults that work across RP2040/RP2350
    and ESP32-S3.
    """

    def __init__(
        self,
        *,
        sda: int,
        scl: int,
        address: int = 0x29,
        skip_spad_info: bool = True,
        interrupt_status_mask: int = 0xFF,
    ) -> None:
        """Create a VL53L0X driver from flat pin numbers.

        Args:
            sda: GPIO number for the I²C data line.
            scl: GPIO number for the I²C clock line.
            address: 7-bit I²C address; default 0x29.
            skip_spad_info: Bypass the SPAD-count read; default True.
            interrupt_status_mask: Mask for the interrupt-status poll; default
                0xFF to cover both RP2040 (bits 0-2) and ESP32-S3 (bit 6).

        Raises:
            DeviceNotFoundError: Nothing ACKed at ``address`` on the scanned bus.
        """
        # Soft I²C: the VL53L0X clock-stretches heavily during the firmware
        # upload, which the hardware peripheral aborts on.
        i2c = soft_i2c(sda, scl)
        if address not in i2c.scan():
            raise DeviceNotFoundError(f"VL53L0X not found at 0x{address:02x}")
        _soft_reset(i2c, address)
        super().__init__(i2c, address, skip_spad_info, interrupt_status_mask)


def _soft_reset(i2c: object, address: int) -> None:
    """Reboot the chip and poll until it signals ready (best-effort).

    Clears any half-init state from a previous attempt before init() touches
    calibration registers. A NACK or a no-show is swallowed — init() runs
    regardless, matching the chip's tolerance for a skipped reset.
    """
    try:
        i2c.writeto_mem(address, SOFT_RESET_GO2_SOFT_RESET_N, b"\x00")
        utime.sleep_ms(_SOFT_RESET_PAUSE_MS)
        i2c.writeto_mem(address, SOFT_RESET_GO2_SOFT_RESET_N, b"\x01")
        utime.sleep_ms(_SOFT_RESET_PAUSE_MS)
        for _ in range(_SOFT_RESET_POLLS):
            if i2c.readfrom_mem(address, IDENTIFICATION_MODEL_ID, 1)[0] == _MODEL_ID_BOOTED:
                return
            utime.sleep_ms(_SOFT_RESET_PAUSE_MS)
    except OSError:
        return


__all__ = ["VL53L0X", "DeviceNotFoundError"]
