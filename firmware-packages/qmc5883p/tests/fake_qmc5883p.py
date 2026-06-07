"""Host CPython register-level QMC5883P simulator for use in tests.

Models a flat register file plus the behaviours the driver depends on:
  - CHIP_ID (0x00) returns the configured id at construction (default 0x80).
  - STATUS (0x09) reports DRDY (bit0) and OVL (bit1). `drdy_after(n)` makes the
    next n status reads report not-ready so the driver's poll loop is exercised.
  - DATA (0x01) serves a 6-byte little-endian signed XYZ block, set via
    set_sample(...).

Writes land in the register file and are appended to `writes` so tests can
assert the init sequence. Pure register fake — no NACK retries or clock-stretch
quirks (those need hardware).
"""

from __future__ import annotations

import struct

CHIP_ID_REG = 0x00
DATA_REG = 0x01
STATUS_REG = 0x09

_STATUS_DRDY = 0x01
_STATUS_OVL = 0x02


class FakeQMC5883P:
    """In-memory QMC5883P register file + minimal behaviour for driver tests."""

    def __init__(self, chip_id: int = 0x80) -> None:
        """Initialise the register file with the requested CHIP_ID and a zero sample."""
        self.regs = bytearray(256)
        self.regs[CHIP_ID_REG] = chip_id
        self.writes: list[tuple[int, bytes]] = []
        self._ovl = False
        self._drdy_skip = 0
        self.set_sample(0, 0, 0)

    def set_sample(self, x: int, y: int, z: int) -> None:
        """Pack one raw signed int16 (x, y, z) sample into DATA (little-endian)."""
        block = struct.pack("<hhh", x, y, z)
        for i, b in enumerate(block):
            self.regs[DATA_REG + i] = b

    def set_overflow(self, ovl: bool) -> None:  # noqa: FBT001
        """Set whether STATUS reports the OVL (field-saturation) bit."""
        self._ovl = ovl

    def drdy_after(self, n: int) -> None:
        """Make the next `n` STATUS reads report not-ready, then ready."""
        self._drdy_skip = n

    def _status_byte(self) -> int:
        """Compute the STATUS byte, consuming one `drdy_after` not-ready step."""
        if self._drdy_skip > 0:
            self._drdy_skip -= 1
            drdy = 0
        else:
            drdy = _STATUS_DRDY
        return drdy | (_STATUS_OVL if self._ovl else 0)

    def read(self, reg: int, nbytes: int) -> bytes:
        """Serve a register read; STATUS is computed, all else is the register file."""
        if reg == STATUS_REG:
            return bytes((self._status_byte(),))[:nbytes]
        return bytes(self.regs[reg : reg + nbytes])

    def write(self, reg: int, data: bytes) -> None:
        """Record the write and apply it to the register file."""
        self.writes.append((reg, bytes(data)))
        for i, b in enumerate(data):
            self.regs[reg + i] = b
