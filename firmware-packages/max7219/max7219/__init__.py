"""MCU-micropython MAX7219 8x32 display package — SPI matrix driver.

The caller supplies the SPI id, sck/mosi pins, and the device's chip-select
(from the project's ``BOARD`` wiring table), so the project owns the wiring and
this package claims no pins at import time.

Example:
    from max7219 import connect, DisplayCycle
    display = connect(spi_id=BOARD.spi.id, sck=BOARD.spi.sck,
                      mosi=BOARD.spi.mosi, cs=BOARD.devices["display"].cs)
    cycle = DisplayCycle(display, rtc)  # rtc is a machine.RTC

``connect()`` is the only entry point that touches ``machine``; the driver,
fonts, and DisplayCycle are pure logic, so importing this package stays safe in
the host CPython test environment.
"""

from max7219.display_cycle import DisplayCycle, day_name, format_time_12h, show_time
from max7219.max7219 import MAX7219

__all__ = ["MAX7219", "DisplayCycle", "connect", "day_name", "format_time_12h", "show_time"]


def connect(*, spi_id: int, sck: int, mosi: int, cs: int) -> MAX7219:
    """Open the SPI bus on the given pins and return a ready-to-use display.

    Args:
        spi_id: The SPI peripheral instance (e.g. ``BOARD.spi.id``).
        sck: Shared SPI clock GPIO (``BOARD.spi.sck``).
        mosi: Shared SPI data-out GPIO → matrix DIN (``BOARD.spi.mosi``).
        cs: This display's chip-select GPIO (``BOARD.devices["display"].cs``);
            a write-only device needs no MISO.

    Returns:
        A MAX7219 driving the 8x32 chain. CS idles high (active-low).
    """
    from machine import SPI, Pin  # noqa: PLC0415

    spi = SPI(spi_id, baudrate=1_000_000, polarity=0, phase=0, sck=Pin(sck), mosi=Pin(mosi))
    return MAX7219(spi, Pin(cs, Pin.OUT, value=1))
