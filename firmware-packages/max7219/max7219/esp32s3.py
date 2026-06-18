"""MCU-micropython backend for the ESP32-S3 SPI bus driving the MAX7219 chain.

SCK=GPIO12, MOSI/DIN=GPIO11, CS=GPIO10 (the FSPI defaults). Chosen to avoid the
UART1 GPS pins (GPIO17/GPIO18); MISO is unused by a write-only display.
"""

from machine import SPI, Pin

spi: SPI = SPI(1, baudrate=1_000_000, polarity=0, phase=0, sck=Pin(12), mosi=Pin(11))
cs: Pin = Pin(10, Pin.OUT, value=1)  # active-low; idle high
