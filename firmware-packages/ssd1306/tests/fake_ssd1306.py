"""Host CPython I²C target fake for SSD1306 driver tests."""

from __future__ import annotations


class FakeSSD1306:
    """Record raw command and framebuffer writes sent to an SSD1306 address."""

    def __init__(self) -> None:
        """Initialise an empty raw-write log."""
        self.writes: list[bytes] = []

    def write_raw(self, data: bytes) -> None:
        """Append one raw I²C transaction to the write log.

        Args:
            data: Complete transaction payload, including the control byte.
        """
        self.writes.append(bytes(data))
