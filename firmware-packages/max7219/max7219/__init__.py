"""MCU-micropython MAX7219 package — SPI driver for an 8xN LED-matrix chain.

The caller supplies the SPI id, sck/mosi pins, and the display's chip-select
(from the project's ``BOARD`` wiring table), so the project owns the wiring and
this package claims no pins at import time. ``connect`` is the only entry point
that touches ``machine``; ``MAX7219`` and the font are pure logic, so importing
this package stays safe in the host CPython test environment.

Example:
    from max7219 import connect
    top = connect(spi_id=1, sck=10, mosi=11, cs=9, num_modules=4)
    top.show_text("top 123")
"""

from max7219.max7219 import MAX7219

__all__ = ["MAX7219", "connect"]


def connect(*, spi_id: int, sck: int, mosi: int, cs: int, num_modules: int = 4) -> MAX7219:
    """Open the SPI bus on the given pins and return a ready-to-use display.

    Args:
        spi_id: The SPI peripheral instance (e.g. ``BOARD.display_top.spi_id``).
        sck: SPI clock GPIO for this chain.
        mosi: SPI data-out GPIO → matrix DIN.
        cs: This display's chip-select GPIO; a write-only device needs no MISO.
        num_modules: Number of 8x8 modules in the cascade (default 4).

    Returns:
        A MAX7219 driving the chain. CS idles high (active-low).
    """
    from machine import SPI, Pin  # noqa: PLC0415

    spi = SPI(spi_id, baudrate=1_000_000, polarity=0, phase=0, sck=Pin(sck), mosi=Pin(mosi))
    return MAX7219(spi, Pin(cs, Pin.OUT, value=1), num_modules=num_modules)
