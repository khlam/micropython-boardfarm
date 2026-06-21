"""MCU-micropython ATGM336H package — a UART NMEA reader.

The constructor takes flat pin numbers and opens its own UART, so the project's
BOARD table supplies only pins. UART has no address scan, so the driver probes
the line at construction: a wired ATGM336H streams NMEA sentences continuously
(even without a fix), so if no bytes arrive within ``probe_ms`` the module is
unwired/unpowered and ``DeviceNotFoundError`` is raised — letting the project's retry
loop tell "nothing connected" from a later read error.

Example:
    from atgm336h import GPS, DeviceNotFoundError
    gps = GPS(bus_id=0, tx=0, rx=1)   # UART opened + probed here
    line = gps.readline()          # "$GPRMC,..." or None on timeout
"""

import utime

__all__ = ["GPS", "DeviceNotFoundError"]

# Default probe budget. The ATGM336H emits at least one sentence per second, so
# ~2 s reliably catches a wired module while staying short on a dead line.
_PROBE_MS = 2_000
_PROBE_POLL_MS = 10


class DeviceNotFoundError(Exception):
    """No NMEA bytes arrived on the UART within the probe budget.

    Raised (instead of a generic exception) so a project's retry loop can tell
    "nothing connected" — bad wiring, power, or TX/RX swap — apart from a
    transient read error once streaming.
    """


class GPS:
    """NMEA sentence reader over a UART the driver opens from flat pins."""

    def __init__(self, *, bus_id: int, tx: int, rx: int, probe_ms: int = _PROBE_MS) -> None:
        """Open the wired UART at 9600 baud and confirm the module is alive.

        Args:
            bus_id: Selects the UART peripheral.
            tx: GPIO number driving the GPS RX line.
            rx: GPIO number carrying the NMEA stream back.
            probe_ms: How long to wait for the first bytes before giving up.
        """
        from machine import UART, Pin  # noqa: PLC0415

        self._uart = UART(bus_id, baudrate=9600, tx=Pin(tx), rx=Pin(rx), timeout=100)
        self._probe(probe_ms)

    def _probe(self, probe_ms: int) -> None:
        """Wait for the first byte line; raise DeviceNotFoundError if none arrives."""
        t_start = utime.ticks_ms()
        while utime.ticks_diff(utime.ticks_ms(), t_start) < probe_ms:
            if self._uart.readline() is not None:
                return
            utime.sleep_ms(_PROBE_POLL_MS)
        raise DeviceNotFoundError(f"no NMEA bytes within {probe_ms} ms")

    def readline(self) -> str | None:
        """Read one NMEA sentence from UART.

        Returns:
            The decoded sentence string (e.g. ``"$GPRMC,..."``), or ``None``
            when the UART timeout fires before a newline arrives or when the
            bytes cannot be decoded as ASCII or do not start with ``$``.
        """
        return _parse_line(self._uart.readline())


def _parse_line(raw: bytes | None) -> str | None:
    """Decode and validate one raw UART line as an NMEA sentence.

    Args:
        raw: Raw bytes from ``UART.readline()``, or ``None`` on timeout.

    Returns:
        The stripped sentence if it decodes as ASCII and starts with ``$``,
        else ``None`` (timeout, decode error, or non-NMEA line).
    """
    if raw is None:
        return None
    try:
        line = raw.decode().strip()
    except (ValueError, UnicodeError):
        return None
    return line if line.startswith("$") else None
