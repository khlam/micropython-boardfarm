"""Local test doubles for the max7219 driver and display-cycle tests.

No ``machine`` stub is needed: the driver accepts any object exposing
``write``/``on``/``off``, and DisplayCycle accepts any object with ``datetime``
and the display methods it calls.
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


class FakeRTC:
    """RTC stand-in returning a fixed ``datetime`` 8-tuple."""

    def __init__(self, dt: tuple) -> None:
        """Store the tuple ``(year, month, day, weekday, hour, minute, second, sub)``."""
        self._dt = dt

    def datetime(self) -> tuple:
        """Return the stored datetime tuple."""
        return self._dt


class FakeDisplay:
    """Display stand-in that records the cycle's render calls in order."""

    def __init__(self) -> None:
        """Start with no recorded calls."""
        self.calls: list[tuple] = []

    def show_time(self, text: str, suffix: str, *_fonts: object) -> None:
        """Record a time render."""
        self.calls.append(("show_time", text, suffix))

    def show_auto(self, text: str, _fn: object = None) -> None:
        """Record an auto/centered render."""
        self.calls.append(("show_auto", text))

    def wiggle_step(self) -> None:
        """Record a wiggle advance."""
        self.calls.append(("wiggle_step",))
