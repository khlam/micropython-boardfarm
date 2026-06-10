"""MCU-micropython ATGM336H package — chip-dispatched UART NMEA reader.

Example:
    from atgm336h import connect
    gps = connect()          # chip-specific UART initialised here
    line = gps.readline()    # "$GPRMC,..." or None on timeout
"""

import os

__all__ = ["GPS", "connect"]


class GPS:
    """NMEA sentence reader that wraps a chip-specific UART instance."""

    def __init__(self, uart: object) -> None:
        """Store the UART instance for later reads.

        Args:
            uart: A ``machine.UART`` instance configured at 9600 baud with a
                short timeout so readline() returns without blocking the loop.
        """
        self._uart = uart

    def readline(self) -> str | None:
        """Read one NMEA sentence from UART.

        Returns:
            The decoded sentence string (e.g. ``"$GPRMC,..."``), or ``None``
            when the UART timeout fires before a newline arrives or when the
            bytes cannot be decoded as ASCII or do not start with ``$``.
        """
        raw = self._uart.readline()
        if raw is None:
            return None
        try:
            line = raw.decode().strip()
        except (ValueError, UnicodeError):
            return None
        return line if line.startswith("$") else None


def connect() -> "GPS":
    """Open the chip-specific UART and return a ready-to-use GPS instance.

    Returns:
        A GPS instance wrapping the chip-specific UART.
    """
    _machine = os.uname().machine
    if "ESP32S3" in _machine:
        from atgm336h.esp32s3 import uart as _uart  # noqa: PLC0415
    elif "RP2350" in _machine:
        from atgm336h.rp2350 import uart as _uart  # noqa: PLC0415
    else:
        from atgm336h.rp2040 import uart as _uart  # noqa: PLC0415
    return GPS(_uart)
