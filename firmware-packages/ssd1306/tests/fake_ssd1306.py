"""Host CPython register-level SSD1306 simulator for use in tests.

Models the write-only I²C interface the driver uses: every transfer arrives
as ``write(control, payload)`` where ``control`` is the SSD1306 control byte
(0x00 command stream, 0x40 GDDRAM data). Command bytes accumulate in
``commands`` (flat) and ``command_writes`` (one tuple per stream); data writes
land in the ``gddram`` framebuffer, which ``pixel()`` decodes for assertions.

Pure interface fake — no charge-pump timing, no NACK behaviour. Those need
hardware.
"""

from __future__ import annotations

_PAGE_HEIGHT = 8


class FakeSSD1306:
    """In-memory SSD1306 GDDRAM + command log for driver tests."""

    def __init__(self, width: int = 128, height: int = 64) -> None:
        """Allocate a GDDRAM buffer matching the simulated panel geometry."""
        self.width = width
        self.height = height
        self.pages = height // _PAGE_HEIGHT
        self.commands: list[int] = []
        self.command_writes: list[tuple[int, ...]] = []
        self.gddram = bytearray(width * self.pages)
        self.show_count = 0

    def write(self, reg: int, data: bytes) -> None:
        """Route a transfer by its control byte to the command log or GDDRAM."""
        if reg == 0x00:
            self.commands.extend(data)
            self.command_writes.append(tuple(data))
        elif reg == 0x40:
            self.gddram[: len(data)] = data
            self.show_count += 1

    def pixel(self, x: int, y: int) -> int:
        """Return the on/off state (1/0) of the pixel at (x, y) from GDDRAM."""
        index = x + (y >> 3) * self.width
        return (self.gddram[index] >> (y & 0x07)) & 1
