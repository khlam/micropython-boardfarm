"""MCU-micropython register-level driver for the InvenSense MPU6050 family IMU.

Covers the MPU6050, MPU6500, and MPU9250 — all three share the accel +
gyro register map and only differ in WHO_AM_I and the temperature
transfer function. The driver auto-detects the chip via WHO_AM_I and
applies the right temperature scale + offset accordingly.

Chip-agnostic with respect to the MCU: takes a `machine.I2C` (or
`SoftI2C`) instance from the caller and never imports `machine` itself.
"""

import struct

from micropython import const

_WHO_AM_I = const(0x75)
_PWR_MGMT_1 = const(0x6B)
_SMPLRT_DIV = const(0x19)
_CONFIG = const(0x1A)
_GYRO_CONFIG = const(0x1B)
_ACCEL_CFG = const(0x1C)
_ACCEL_XOUT = const(0x3B)

_ACCEL_LSB_PER_G = 16384.0
_GYRO_LSB_PER_DPS = 131.0

# WHO_AM_I -> (chip name, temp scale, temp offset °C).
# MPU6500/MPU9250 are register-compatible with MPU6050 for accel + gyro,
# but use a different temperature transfer function. Many "MPU6050"
# breakouts on AliExpress actually contain MPU6500 silicon (WHO_AM_I=0x70).
_KNOWN = {
    0x68: ("MPU6050", 340.0, 36.53),
    0x70: ("MPU6500", 333.87, 21.0),
    0x71: ("MPU9250", 333.87, 21.0),
}


class MPU6050:
    """Configured ±2 g / ±250 °/s ranges with 44 Hz DLPF, 125 Hz internal sample rate.

    Attributes:
        i2c: The bus passed by the caller.
        addr: 7-bit I²C address (0x68 or 0x69 depending on AD0).
        kind: One of "MPU6050", "MPU6500", or "MPU9250" — set after the
            WHO_AM_I dispatch at construction.
        last_saturated: Set by `read_all()` to True if any raw axis hit
            the int16 rail on the most recent sample (range exceeded).
    """

    def __init__(self, i2c: object, addr: int = 0x68) -> None:
        """Detect the chip via WHO_AM_I and write the standard init sequence.

        Args:
            i2c: A `machine.I2C` or `SoftI2C` (anything with
                `readfrom_mem` / `writeto_mem` / `readfrom_mem_into`).
            addr: 7-bit I²C address — 0x68 (AD0=GND/floating) or 0x69
                (AD0=3V3).

        Raises:
            OSError: WHO_AM_I returns a value not in the known table
                (counterfeit chip or wrong device on the bus).
        """
        self.i2c = i2c
        self.addr = addr
        self._buf = bytearray(14)
        self.last_saturated = False

        who = self.i2c.readfrom_mem(addr, _WHO_AM_I, 1)[0]
        if who not in _KNOWN:
            raise OSError(f"Unknown IMU WHO_AM_I=0x{who:02x}")
        self.kind, self._t_scale, self._t_offset = _KNOWN[who]

        self._w(_PWR_MGMT_1, 0x00)
        self._w(_SMPLRT_DIV, 0x07)
        self._w(_CONFIG, 0x03)
        self._w(_GYRO_CONFIG, 0x00)
        self._w(_ACCEL_CFG, 0x00)

    def _w(self, reg: int, val: int) -> None:
        """Write a single byte `val` to register `reg` on this device."""
        self.i2c.writeto_mem(self.addr, reg, bytes((val,)))

    def read_all(self) -> tuple[float, float, float, float, float, float, float]:
        """Read one full sample and return it in physical units.

        Reads the 14-byte ACCEL_XOUT block in one transaction (3 accel
        axes, 1 temp, 3 gyro axes — all big-endian int16). Sets
        `self.last_saturated` if any raw axis pegged at the int16 rail.

        Returns:
            7-tuple `(ax, ay, az, gx, gy, gz, temp_c)`:
              - accel in *g* (gravity units),
              - gyro in *°/s*,
              - temp in *°C* via the chip's transfer function.
        """
        self.i2c.readfrom_mem_into(self.addr, _ACCEL_XOUT, self._buf)
        ax, ay, az, t, gx, gy, gz = struct.unpack(">hhhhhhh", self._buf)
        # Any raw axis pegged at int16 rails means the configured
        # ±2 g / ±250 °/s range was exceeded — LSBs clip and the
        # physical reading is no longer meaningful. main.py
        # edge-triggers a diag on this.
        self.last_saturated = (
            ax >= 32767
            or ax <= -32768
            or ay >= 32767
            or ay <= -32768
            or az >= 32767
            or az <= -32768
            or gx >= 32767
            or gx <= -32768
            or gy >= 32767
            or gy <= -32768
            or gz >= 32767
            or gz <= -32768
        )
        return (
            ax / _ACCEL_LSB_PER_G,
            ay / _ACCEL_LSB_PER_G,
            az / _ACCEL_LSB_PER_G,
            gx / _GYRO_LSB_PER_DPS,
            gy / _GYRO_LSB_PER_DPS,
            gz / _GYRO_LSB_PER_DPS,
            t / self._t_scale + self._t_offset,
        )
