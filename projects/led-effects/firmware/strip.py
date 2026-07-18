"""Project-local WS2812B strip driver."""

from machine import Pin
from neopixel import NeoPixel


class Strip:
    """Own a NeoPixel buffer and latch effect frames to the strip."""

    def __init__(self, count: int, *, pin: int) -> None:
        """Build a strip on the caller-selected data GPIO.

        Args:
            count: Number of LEDs on the strip.
            pin: GPIO number carrying the strip's data signal.
        """
        self.count = count
        self._np = NeoPixel(Pin(pin, Pin.OUT), count)

    def render(self, frame: list[tuple[int, int, int]]) -> None:
        """Buffer one RGB tuple per LED and latch the complete frame.

        Args:
            frame: Colours in physical strip order.
        """
        for i in range(self.count):
            self._np[i] = frame[i]
        self._np.write()
