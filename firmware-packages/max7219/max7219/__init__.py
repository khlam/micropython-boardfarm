"""MCU-micropython MAX7219 8x32 display package — chip-dispatched SPI backend.

Example:
    from max7219 import connect, DisplayCycle
    display = connect()                 # chip-specific SPI + CS initialised here
    cycle = DisplayCycle(display, rtc)  # rtc is a machine.RTC

``connect()`` is the only entry point that touches ``machine``; the driver,
fonts, and DisplayCycle are pure logic, so importing this package stays safe in
the host CPython test environment.
"""

import os

from max7219.display_cycle import DisplayCycle, day_name, format_time_12h, show_time
from max7219.max7219 import MAX7219

__all__ = ["MAX7219", "DisplayCycle", "connect", "day_name", "format_time_12h", "show_time"]


def connect() -> MAX7219:
    """Open the chip-specific SPI bus and return a ready-to-use display.

    Returns:
        A MAX7219 driving the 8x32 chain on this chip's SPI pins.
    """
    _machine = os.uname().machine
    if "ESP32S3" in _machine:
        from max7219.esp32s3 import cs, spi  # noqa: PLC0415
    elif "RP2350" in _machine:
        from max7219.rp2350 import cs, spi  # noqa: PLC0415
    else:
        from max7219.rp2040 import cs, spi  # noqa: PLC0415
    return MAX7219(spi, cs)
