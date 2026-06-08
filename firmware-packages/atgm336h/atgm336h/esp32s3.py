"""MCU-micropython backend for the ESP32-S3 UART1 bus (GPIO17=TX, GPIO18=RX) at 9600 baud."""

from machine import UART

# ATGM336H TX → GPIO18 (MCU RX). GPIO17 (MCU TX) is optional for NMEA commands.
# timeout=100 ms keeps readline() non-blocking so the 10-second collection window
# can check elapsed time between calls without stalling.
uart: UART = UART(1, baudrate=9600, tx=17, rx=18, timeout=100)
