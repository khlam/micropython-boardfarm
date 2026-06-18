"""MCU-micropython ATGM336H package — UART NMEA reader.

The caller supplies the UART id and tx/rx pins (from ``board_pinout.BOARD``), so
the project owns the wiring and this package claims no pins at import time.

Example:
    from board_pinout import BOARD
    from atgm336h import connect
    gps = connect(uart_id=BOARD.uart.id, tx=BOARD.uart.tx, rx=BOARD.uart.rx)
    line = gps.readline()    # "$GPRMC,..." or None on timeout
"""

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


def connect(*, uart_id: int, tx: int, rx: int) -> "GPS":
    """Open the UART on the given pins and return a ready-to-use GPS instance.

    Args:
        uart_id: The UART peripheral instance (e.g. ``BOARD.uart.id``).
        tx: GPIO for MCU TX → GPS RX (optional on the wire, required by the
            constructor).
        rx: GPIO for MCU RX ← GPS TX (carries the NMEA stream).

    Returns:
        A GPS instance wrapping a UART configured at 9600 baud with a short
        timeout so readline() returns without blocking the loop.
    """
    from machine import UART, Pin  # noqa: PLC0415

    uart = UART(uart_id, baudrate=9600, tx=Pin(tx), rx=Pin(rx), timeout=100)
    return GPS(uart)
