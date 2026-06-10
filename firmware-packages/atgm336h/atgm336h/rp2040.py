"""MCU-micropython backend for the RP2040 UART0 bus (GP0=TX, GP1=RX) at 9600 baud."""

from machine import UART, Pin

# ATGM336H TX → GP1 (MCU RX). GP0 (MCU TX) is optional for sending NMEA commands.
# timeout=100 ms keeps readline() non-blocking so the 10-second collection window
# can check elapsed time between calls without stalling.
uart: UART = UART(0, baudrate=9600, tx=Pin(0), rx=Pin(1), timeout=100)
