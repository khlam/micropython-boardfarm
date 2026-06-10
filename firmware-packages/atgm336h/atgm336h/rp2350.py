"""MCU-micropython backend for the RP2350 UART0 bus (GP0=TX, GP1=RX) at 9600 baud."""

from machine import UART, Pin

# Same pin layout as RP2040-Zero / RP2350-Zero.
# timeout=100 ms keeps readline() non-blocking so the 10-second collection window
# can check elapsed time between calls without stalling.
uart: UART = UART(0, baudrate=9600, tx=Pin(0), rx=Pin(1), timeout=100)
