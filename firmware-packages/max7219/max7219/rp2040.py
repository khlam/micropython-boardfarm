"""MCU-micropython backend for the RP2040 SPI0 bus driving the MAX7219 chain.

SCK=GP18, MOSI/DIN=GP19, CS=GP17. Disjoint from the UART0 GPS pins (GP0/GP1), so
the display and GPS never contend for a pin.
"""

from machine import SPI, Pin

# Mode 0 (polarity=0, phase=0). 1 MHz is well within the MAX7219's 10 MHz limit
# and keeps the SPI writes short enough not to stall the display/GPS loop.
spi: SPI = SPI(0, baudrate=1_000_000, polarity=0, phase=0, sck=Pin(18), mosi=Pin(19))
cs: Pin = Pin(17, Pin.OUT, value=1)  # active-low; idle high
