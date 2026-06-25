"""MCU MicroPython MAX7219 package exposing a universal display facade."""

from max7219.max7219 import _MAX7219Backend
from pixel_display import Display

__all__ = ["MAX7219"]

_WIDTH_PIXELS = 32
_HEIGHT_PIXELS = 16


class MAX7219:
    """Open a MAX7219 SPI chain from flat pins and expose ``show(frame)``."""

    def __init__(  # noqa: PLR0913 - flat display config mirrors project BOARD tables.
        self,
        *,
        spi_id: int,
        sck: int,
        mosi: int,
        cs: int,
        width_pixels: int = _WIDTH_PIXELS,
        height_pixels: int = _HEIGHT_PIXELS,
        brightness: float = 1.0,
        allow_lossy: bool = False,
        failure_mode: str = "corner_xs",
    ) -> None:
        """Open SPI and bind the hardware backend to ``pixel_display.Display``.

        Args:
            spi_id: SPI peripheral instance.
            sck: SPI clock GPIO.
            mosi: SPI data-out GPIO.
            cs: Chain chip-select GPIO.
            width_pixels: Declared project display width.
            height_pixels: Declared project display height.
            brightness: Normalized output brightness.
            allow_lossy: Whether backend conversion may discard detail.
            failure_mode: ``"corner_xs"`` or ``"blank"``.
        """
        from machine import SPI, Pin  # noqa: PLC0415

        spi = SPI(spi_id, baudrate=1_000_000, polarity=0, phase=0, sck=Pin(sck), mosi=Pin(mosi))
        backend = _MAX7219Backend(spi, Pin(cs, Pin.OUT, value=1))
        self._display = Display(
            backend,
            width_pixels=width_pixels,
            height_pixels=height_pixels,
            brightness=brightness,
            allow_lossy=allow_lossy,
            failure_mode=failure_mode,
        )

    @property
    def width_pixels(self) -> int:
        """Return the declared visual display width."""
        return self._display.width_pixels

    @property
    def height_pixels(self) -> int:
        """Return the declared visual display height."""
        return self._display.height_pixels

    def show(self, frame: object) -> None:
        """Render one abstract pixel frame."""
        self._display.show(frame)

    def flip(self) -> None:
        """Rotate the display 180 degrees, re-rendering the current frame."""
        self._display.flip()
