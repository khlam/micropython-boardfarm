"""Local test doubles for the max7219 driver.

No ``machine`` stub is needed: the driver accepts any object exposing
``write`` (SPI) and ``on``/``off`` (chip-select).
"""

from __future__ import annotations


class FakeSPI:
    """SPI stand-in that records each ``write`` payload as bytes."""

    def __init__(self) -> None:
        """Start with no recorded writes."""
        self.writes: list[bytes] = []

    def write(self, buf: bytes) -> None:
        """Record one SPI write."""
        self.writes.append(bytes(buf))


class FakeCS:
    """Chip-select stand-in that records the sequence of on/off toggles."""

    def __init__(self) -> None:
        """Start idle (logically high) with no recorded toggles."""
        self.toggles: list[str] = []

    def on(self) -> None:
        """Record a CS high (idle)."""
        self.toggles.append("on")

    def off(self) -> None:
        """Record a CS low (asserted)."""
        self.toggles.append("off")
