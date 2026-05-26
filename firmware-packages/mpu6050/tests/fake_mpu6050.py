"""Host CPython register-level MPU6050 family simulator for use in tests.

Models a flat register file plus the two behaviours the driver depends
on:
  - WHO_AM_I (0x75) returns the configured chip id at construction
    (default 0x68 → "MPU6050"; 0x70 → "MPU6500"; 0x71 → "MPU9250").
  - ACCEL_XOUT (0x3B) serves a 14-byte block (ax, ay, az, temp, gx, gy,
    gz — all big-endian int16). Tests poke this via `set_sample(...)`.

Pure register fake — does not exercise NACK retries, clock-stretch
timeouts, or other silicon quirks. Those need hardware.
"""

from __future__ import annotations

import struct

WHO_AM_I_REG = 0x75
ACCEL_XOUT_REG = 0x3B


class FakeMPU6050:
    """In-memory MPU6050 register file + minimal behaviour for driver tests."""

    def __init__(self, who_am_i: int = 0x68) -> None:
        """Initialise the register file with the requested chip id at WHO_AM_I."""
        self.regs = bytearray(256)
        self.regs[WHO_AM_I_REG] = who_am_i
        # Default sample: stationary, ~1 g on Z, 0 °/s, 0 raw temp.
        self.set_sample(0, 0, 16384, 0, 0, 0, 0)

    def set_sample(
        self,
        ax: int,
        ay: int,
        az: int,
        gx: int,
        gy: int,
        gz: int,
        temp_raw: int,
    ) -> None:
        """Pack one raw int16 sample into the ACCEL_XOUT block.

        Args:
            ax: raw accel X LSBs (signed 16-bit; 16384 LSB ≙ 1 g).
            ay: raw accel Y LSBs (signed 16-bit; 16384 LSB ≙ 1 g).
            az: raw accel Z LSBs (signed 16-bit; 16384 LSB ≙ 1 g).
            gx: raw gyro X LSBs (signed 16-bit; 131 LSB ≙ 1 °/s).
            gy: raw gyro Y LSBs (signed 16-bit; 131 LSB ≙ 1 °/s).
            gz: raw gyro Z LSBs (signed 16-bit; 131 LSB ≙ 1 °/s).
            temp_raw: raw temperature LSBs (chip-specific transfer).
        """
        block = struct.pack(">hhhhhhh", ax, ay, az, temp_raw, gx, gy, gz)
        for i, b in enumerate(block):
            self.regs[ACCEL_XOUT_REG + i] = b

    def read(self, reg: int, nbytes: int) -> bytes:
        """Return `nbytes` from the register file starting at `reg`."""
        return bytes(self.regs[reg : reg + nbytes])

    def write(self, reg: int, data: bytes) -> None:
        """Write `data` to the register file. No side effects in this fake."""
        for i, b in enumerate(data):
            self.regs[reg + i] = b
