"""Host CPython register-level VL53L0X simulator for use in tests.

Models the chip as a flat 256-byte register file plus a handful of
behaviours the driver relies on during init/start/read:

  - 0xBF (SOFT_RESET): write 0 then 1 boots; 0xC0 returns 0xEE when booted.
  - 0x83 (SPAD-info status): becomes non-zero after the trigger sequence
    in `_spad_info()` so the poll loop exits. Skipped when the driver
    constructs with `skip_spad_info=True`.
  - 0x13 (RESULT_INTERRUPT_STATUS): set the masked bits after writes to
    0x00 (SYSRANGE_START) so calibration + read polls exit.
  - 0x1E/0x1F (RESULT_RANGE_STATUS+10): big-endian distance in mm. Tests
    set this via `set_distance(mm)` before calling `tof.read()`.

The point is *driver logic* coverage — sequencing, retries, mask handling,
skip_spad_info. Real chip quirks (NACKs, clock-stretch timeouts) are
out of scope; tests that need those have to run on real hardware.
"""

from __future__ import annotations


class FakeVL53L0X:
    """In-memory VL53L0X register file + minimal behaviour for driver tests."""

    MODEL_ID = 0xEE

    def __init__(self, *, interrupt_status_after_write: int = 0x07) -> None:
        """Initialise the register file with default boot-time values.

        Args:
            interrupt_status_after_write: Bits to set in 0x13 after every
                write to 0x00 (SYSRANGE_START). Tests covering the ESP32
                wide-mask path pass 0x40 here.
        """
        self.regs = bytearray(256)
        self.regs[0xC0] = self.MODEL_ID  # identification model id
        # Driver reads 0x91 during init as `_stop_variable`. Any byte works.
        self.regs[0x91] = 0x00
        # `_spad_info()` polls 0x83 until non-zero, then reads SPAD info from
        # 0x92. We expose both so the non-skip path is testable too.
        self.regs[0x92] = 0x0A  # count=10, is_aperture=0
        # Distance is read from 0x1E/0x1F (big-endian).
        self.set_distance(0)
        self._irq_set_bits = interrupt_status_after_write

    def set_distance(self, mm: int) -> None:
        """Set the simulated big-endian 16-bit distance reading at 0x1E/0x1F."""
        self.regs[0x1E] = (mm >> 8) & 0xFF
        self.regs[0x1F] = mm & 0xFF

    def read(self, reg: int, nbytes: int) -> bytes:
        """Return `nbytes` from the register file starting at `reg`."""
        return bytes(self.regs[reg : reg + nbytes])

    def write(self, reg: int, data: bytes) -> None:
        """Write `data` to the register file, applying behavioural side-effects."""
        # SOFT_RESET sequence: write 0 then 1 keeps model-id reachable.
        # (No state actually changes — the model_id stays 0xEE throughout.)
        if reg == 0x00 and data and (data[0] & 0x01):
            # Starting a measurement / calibration step. Arm interrupt bits.
            self.regs[0x13] |= self._irq_set_bits
        if reg == 0x83 and data == b"\x00":
            # The driver writes 0 then polls until non-zero, mimicking the
            # SPAD-info status handshake.
            self.regs[0x83] = 0x01
        for i, b in enumerate(data):
            self.regs[reg + i] = b
