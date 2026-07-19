"""MicroPython driver for SSD1306 monochrome OLED displays over I²C.

The public driver accepts flat GPIO pin numbers, opens its own software-I²C
bus, and verifies that the configured display address is present. Projects do
not construct or pass bus objects.
"""

from i2c_bus import DeviceNotFoundError
from ssd1306.ssd1306 import SSD1306

__all__ = ["SSD1306", "DeviceNotFoundError"]
