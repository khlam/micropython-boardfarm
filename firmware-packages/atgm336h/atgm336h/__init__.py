"""MCU-micropython ATGM336H package — chip-dispatched UART NMEA reader for the ATGM336H.

Example:
    from atgm336h import gps          # ready-to-use GPS instance, chip UART configured
    line = gps.readline()             # "$GPRMC,..." or None on timeout
"""

from __future__ import annotations

import os

from atgm336h.atgm336h import GPS

_machine = os.uname().machine
if "ESP32S3" in _machine:
    from atgm336h.esp32s3 import uart as _uart
elif "RP2350" in _machine:
    from atgm336h.rp2350 import uart as _uart
else:
    from atgm336h.rp2040 import uart as _uart

gps = GPS(_uart)

__all__ = ["GPS", "gps"]
