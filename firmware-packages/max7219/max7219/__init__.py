"""MCU-micropython MAX7219 package — SPI driver for a 16x32 LED matrix.

Takes flat pin numbers and opens its own SPI bus. The 16x32 display is two
8x32 panels daisy-chained on one SPI bus (MCU -> top panel -> bottom panel).

MAX7219 is a write-only device with no scannable address, so there is no
``DeviceNotFoundError``. If the chain is unwired, init writes succeed
silently — the failure surfaces visually (no LEDs light).

Example:
    from max7219 import MAX7219
    display = MAX7219(spi_id=1, sck=10, mosi=11, cs=9)
    display.show_lines("TOP", "bot")
"""

from max7219.max7219 import MAX7219 as _Max7219Base  # noqa: N811

__all__ = ["MAX7219"]


class MAX7219(_Max7219Base):
    """Framebuffer-backed MAX7219 driver that opens SPI from flat pin numbers.

    Wraps the base driver, adding bus creation so callers pass only plain
    GPIO numbers (from the project's ``BOARD`` table).
    """

    def __init__(self, *, spi_id: int, sck: int, mosi: int, cs: int) -> None:
        """Open SPI on the given pins and initialise the display chain.

        Args:
            spi_id: The SPI peripheral instance (e.g. ``BOARD.spi_id``).
            sck: SPI clock GPIO for the chain.
            mosi: SPI data-out GPIO -> top panel's DIN.
            cs: The chain's chip-select GPIO; a write-only device needs no MISO.
        """
        from machine import SPI, Pin  # noqa: PLC0415

        spi = SPI(spi_id, baudrate=1_000_000, polarity=0, phase=0, sck=Pin(sck), mosi=Pin(mosi))
        super().__init__(spi, Pin(cs, Pin.OUT, value=1))
