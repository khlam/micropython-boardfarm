"""Host CPython stub of the `neopixel` module that records every (r, g, b) written to each LED."""

from __future__ import annotations

from typing import ClassVar


class NeoPixel:
    """Fake `neopixel.NeoPixel` strip that records every writeout for assertions."""

    instances: ClassVar[list[NeoPixel]] = []

    def __init__(self, pin: object, n: int) -> None:
        """Record the (pin, count) on construction; start with all LEDs off."""
        self.pin = pin
        self.n = n
        self._buf: list[tuple] = [(0, 0, 0)] * n
        self.writes: list[tuple] = []
        NeoPixel.instances.append(self)

    def __setitem__(self, i: int, rgb: tuple) -> None:
        """Set LED `i` to the given (r, g, b) tuple (no hardware write yet)."""
        self._buf[i] = tuple(rgb)

    def __getitem__(self, i: int) -> tuple:
        """Return the buffered (r, g, b) for LED `i`."""
        return self._buf[i]

    def write(self) -> None:
        """Record the current LED 0 colour as a "would-be hardware write"."""
        self.writes.append(self._buf[0])


def reset() -> None:
    """Forget every NeoPixel instance recorded so far."""
    NeoPixel.instances.clear()
