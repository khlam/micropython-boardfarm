"""MCU-micropython ATGM336H package — a UART NMEA reader.

The caller supplies a ``Wiring`` record (the pin schema this package needs); the
project's ``BOARD`` table fills it per chip. Nothing here touches ``os.uname()``
or claims a pin at import time.

Example:
    from atgm336h import Wiring, connect
    gps = connect(Wiring(id=0, tx=0, rx=1))   # UART opened here
    line = gps.readline()                      # "$GPRMC,..." or None on timeout
"""

from collections import namedtuple

__all__ = ["GPS", "Wiring", "connect"]

# Pin schema for the GPS UART. ``id`` selects the UART peripheral, ``tx`` drives
# the GPS RX line, ``rx`` carries the NMEA stream back.
Wiring = namedtuple("Wiring", ("id", "tx", "rx"))


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


def connect(wiring: Wiring) -> "GPS":
    """Open the wired UART at 9600 baud and wrap it in a GPS reader.

    Args:
        wiring: A ``Wiring`` record; ``id`` selects the UART peripheral.

    Returns:
        A GPS instance wrapping a UART configured with a short timeout so
        readline() returns without blocking the loop.
    """
    from machine import UART, Pin  # noqa: PLC0415

    uart = UART(wiring.id, baudrate=9600, tx=Pin(wiring.tx), rx=Pin(wiring.rx), timeout=100)
    return GPS(uart)
