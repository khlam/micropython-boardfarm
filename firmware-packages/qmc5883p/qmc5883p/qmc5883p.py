"""MCU-micropython driver for the QST QMC5883P 3-axis magnetometer (I²C).

Despite the near-identical name this is a different chip from the QMC5883L:
different register map, fixed I²C address 0x2C, and an axis-sign quirk. __init__
verifies the chip-ID, soft-resets, inverts X/Y so the output frame matches the
QMC5883L convention (so atan2(y, x) heading reads the same), selects ±2 G range,
and starts continuous output at 50 Hz with OSR=8 (max in-sensor averaging).
read() blocks on the data-ready bit and returns signed (x, y, z) ints.

Chip-agnostic w.r.t. the MCU: takes a machine.I2C / SoftI2C from the caller and
never imports `machine`.
"""

import struct

import utime
from micropython import const

_REG_CHIP_ID = const(0x00)
_REG_DATA = const(0x01)  # 6 bytes: X/Y/Z LSB,MSB signed little-endian
_REG_STATUS = const(0x09)  # bit0=DRDY, bit1=OVL
_REG_CTRL_1 = const(0x0A)
_REG_CTRL_2 = const(0x0B)
_REG_AXIS_SIGN = const(0x29)

# QMC5883P product-id read back from _REG_CHIP_ID once powered.
_CHIP_ID = const(0x80)

# CTRL_1 = (DSR<<6)|(OSR<<4)|(ODR<<2)|MODE → continuous, 50 Hz, OSR=8.
_CTRL_1_VALUE = const((0b00 << 6) | (0b00 << 4) | (0b01 << 2) | 0b01)
_CTRL_2_RANGE_2G = const(0b11 << 2)
_CTRL_2_SOFT_RESET = const(0x80)
_AXIS_SIGN_VALUE = const(0x06)  # invert X/Y → QMC5883L-compatible frame

_STATUS_DRDY = const(0x01)
_RESET_PAUSE_MS = const(10)
_DRDY_POLL_MS = const(1)


class QMC5883P:
    """QMC5883P magnetometer in ±2 G continuous mode at 50 Hz, OSR=8.

    Attributes:
        i2c: The bus passed by the caller.
        address: Fixed 7-bit I²C address (0x2C).
        last_status: STATUS byte from the most recent read(); bit1 (OVL) flags
            field saturation. main.py edge-triggers a diag on it.
    """

    def __init__(self, i2c: object, address: int = 0x2C) -> None:
        """Verify the chip-ID and write the standard init sequence.

        Args:
            i2c: machine.I2C / SoftI2C (readfrom_mem / writeto_mem /
                readfrom_mem_into).
            address: 7-bit I²C address; fixed at 0x2C on this part.

        Raises:
            OSError: CHIP_ID register doesn't read _CHIP_ID (wrong device on the
                bus or a counterfeit part).
        """
        self.i2c = i2c
        self.address = address
        self._buf = bytearray(6)
        self._status = bytearray(1)

        i2c.writeto_mem(address, _REG_CTRL_2, bytes((_CTRL_2_SOFT_RESET,)))
        utime.sleep_ms(_RESET_PAUSE_MS)

        chip_id = i2c.readfrom_mem(address, _REG_CHIP_ID, 1)[0]
        if chip_id != _CHIP_ID:
            raise OSError(f"Unknown QMC5883P CHIP_ID=0x{chip_id:02x}")

        i2c.writeto_mem(address, _REG_AXIS_SIGN, bytes((_AXIS_SIGN_VALUE,)))
        i2c.writeto_mem(address, _REG_CTRL_2, bytes((_CTRL_2_RANGE_2G,)))
        i2c.writeto_mem(address, _REG_CTRL_1, bytes((_CTRL_1_VALUE,)))

    def read_status(self) -> int:
        """Read and cache the STATUS register; return the raw byte."""
        self.i2c.readfrom_mem_into(self.address, _REG_STATUS, self._status)
        return self._status[0]

    @property
    def last_status(self) -> int:
        """STATUS byte from the most recent read_status() / read()."""
        return self._status[0]

    def read(self) -> tuple[int, int, int]:
        """Block until data-ready, then return one signed (x, y, z) sample.

        Self-paced at the 50 Hz ODR (~20 ms/sample), so the caller's loop needs
        no extra sleep.

        Returns:
            (x, y, z) raw signed magnetometer counts (LSB).
        """
        while not (self.read_status() & _STATUS_DRDY):
            utime.sleep_ms(_DRDY_POLL_MS)
        self.i2c.readfrom_mem_into(self.address, _REG_DATA, self._buf)
        return struct.unpack("<hhh", self._buf)
