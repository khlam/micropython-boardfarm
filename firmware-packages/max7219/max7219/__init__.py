"""MCU MicroPython MAX7219 package exposing a universal display facade."""

from max7219.max7219 import _MAX7219Backend
from pixel_display import Display

__all__ = ["MAX7219"]

# Two 8x32 panels stacked. The chain's geometry is fixed by how the panels are
# wired, so it is reported rather than accepted from the caller: the backend can
# only convert frames of exactly this size.
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
        brightness: float = 1.0,
    ) -> None:
        """Open SPI from flat pins and hand the chain to ``pixel_display.Display``.

        Args:
            spi_id: SPI peripheral instance.
            sck: SPI clock GPIO.
            mosi: SPI data-out GPIO.
            cs: Chain chip-select GPIO.
            brightness: Normalized output brightness.
        """
        from machine import SPI, Pin  # noqa: PLC0415

        spi = SPI(spi_id, baudrate=1_000_000, polarity=0, phase=0, sck=Pin(sck), mosi=Pin(mosi))
        super().__init__(
            _MAX7219Backend(spi, Pin(cs, Pin.OUT, value=1)),
            width_pixels=_WIDTH_PIXELS,
            height_pixels=_HEIGHT_PIXELS,
            brightness=brightness,
        )
