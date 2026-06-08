"""Chip-agnostic NMEA sentence reader for the ATGM336H GPS module."""

from __future__ import annotations


class GPS:
    """NMEA sentence reader that wraps a chip-specific UART instance."""

    def __init__(self, uart: object) -> None:
        """Store the UART instance for later reads.

        Args:
            uart: A `machine.UART` instance configured at 9600 baud with a short
                timeout (e.g. 100 ms) so readline() returns without blocking the loop.
        """
        self._uart = uart

    def readline(self) -> str | None:
        """Read one NMEA sentence from UART.

        Returns:
            The decoded sentence string (e.g. ``"$GPRMC,..."``), or ``None``
            when the UART timeout fires before a newline arrives or when the
            received bytes cannot be decoded as ASCII / do not form a valid
            NMEA sentence (i.e. do not start with ``$``).
        """
        raw = self._uart.readline()
        if raw is None:
            return None
        try:
            line = raw.decode().strip()
        except (ValueError, UnicodeError):
            return None
        return line if line.startswith("$") else None
