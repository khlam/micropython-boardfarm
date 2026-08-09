"""Host CPython stub of MicroPython's `neopixel` module."""

from __future__ import annotations

from typing import ClassVar


class NeoPixel:
    """Fake `neopixel.NeoPixel` strip with recorded writes."""

    instances: ClassVar[list[NeoPixel]] = []
    ORDER: ClassVar[tuple] = (1, 0, 2, 3)

    def __init__(self, pin: object, n: int) -> None:
        """Record the (pin, count) on construction; start with all LEDs off."""
        self.pin = pin
        self.n = n
        self.buf = bytearray(n * 3)
        self._buf: list[tuple] = [(0, 0, 0)] * n
        self.writes: list[tuple] = []
        NeoPixel.instances.append(self)

    def __setitem__(self, i: int, rgb: tuple) -> None:
        """Set LED `i` to the given (r, g, b) tuple (no hardware write yet)."""
        self._buf[i] = tuple(rgb)
        offset = i * 3
        for channel in range(3):
            self.buf[offset + self.ORDER[channel]] = rgb[channel]

    def __getitem__(self, i: int) -> tuple:
        """Return the buffered (r, g, b) for LED `i`."""
        return self._buf[i]

    def write(self) -> None:
        """Record the current LED 0 colour as a "would-be hardware write"."""
        self._buf[:] = [
            (
                self.buf[index * 3 + self.ORDER[0]],
                self.buf[index * 3 + self.ORDER[1]],
                self.buf[index * 3 + self.ORDER[2]],
            )
            for index in range(self.n)
        ]
        self.writes.append(self._buf[0])


def reset() -> None:
    """Forget every NeoPixel instance recorded so far."""
    NeoPixel.instances.clear()
