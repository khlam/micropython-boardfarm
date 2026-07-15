"""MCU-micropython WS2812B strip driver.

The data GPIO arrives as a constructor argument from the project's BOARD
table — pin assignments are project wiring, so the package holds no per-chip
configuration and the effects in ``ws2812b.effects`` stay hardware-free.
"""

from machine import Pin
from neopixel import NeoPixel


class Strip:
    """Owns a NeoPixel buffer and latches effect frames to the WS2812B LEDs."""

    def __init__(self, count: int, *, pin: int) -> None:
        """Build a ``count``-LED strip with its data line on GPIO ``pin``.

        Args:
            count: Number of LEDs on the strip.
            pin: GPIO number carrying the strip's DIN line.
        """
        self.count = count
        self._np = NeoPixel(Pin(pin, Pin.OUT), count)

    def render(self, frame: list[tuple[int, int, int]]) -> None:
        """Write one ``frame`` (one ``(r, g, b)`` per LED) to the strip and latch it.

        Args:
            frame: ``count`` colour tuples, as produced by an effect's
                ``frame()``; index ``i`` lights LED ``i``.
        """
        for i in range(self.count):
            self._np[i] = frame[i]
        self._np.write()
