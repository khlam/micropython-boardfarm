"""MCU MicroPython MAX7219 package exposing a universal display facade."""

from max7219.max7219 import _MAX7219Backend
from pixel_display import Display

__all__ = ["MAX7219"]

_WIDTH_PIXELS = 32
_HEIGHT_PIXELS = 16


class MAX7219(Display):
    """A ``pixel_display.Display`` whose backend is a MAX7219 SPI chain."""

    def __init__(
        self,
        *,
        spi_id: int,
        sck: int,
        mosi: int,
        cs: int,
        width_pixels: int = _WIDTH_PIXELS,
        height_pixels: int = _HEIGHT_PIXELS,
        brightness: float = 1.0,
    ) -> None:
        """Open SPI from flat pins and hand the chain to ``pixel_display.Display``.

        Args:
            spi_id: SPI peripheral instance.
            sck: SPI clock GPIO.
            mosi: SPI data-out GPIO.
            cs: Chain chip-select GPIO.
            width_pixels: Declared project display width.
            height_pixels: Declared project display height.
            brightness: Normalized output brightness.
        """
        from machine import SPI, Pin  # noqa: PLC0415

        spi = SPI(spi_id, baudrate=1_000_000, polarity=0, phase=0, sck=Pin(sck), mosi=Pin(mosi))
        super().__init__(
            _MAX7219Backend(spi, Pin(cs, Pin.OUT, value=1)),
            width_pixels=width_pixels,
            height_pixels=height_pixels,
            brightness=brightness,
        )
