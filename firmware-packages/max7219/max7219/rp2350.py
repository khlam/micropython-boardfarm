"""MCU-micropython backend for the RP2350 SPI0 bus driving the MAX7219 chain.

Same wiring as the RP2040-Zero / RP2350-Zero: SCK=GP18, MOSI/DIN=GP19, CS=GP17.
Disjoint from the UART0 GPS pins (GP0/GP1).
"""

from machine import SPI, Pin

spi: SPI = SPI(0, baudrate=1_000_000, polarity=0, phase=0, sck=Pin(18), mosi=Pin(19))
cs: Pin = Pin(17, Pin.OUT, value=1)  # active-low; idle high
