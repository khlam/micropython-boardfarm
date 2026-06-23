"""MCU-micropython ATGM336H package — a UART NMEA reader.

Takes flat pin numbers and opens its own UART. Since UART has no address scan,
the constructor probes the line: a wired ATGM336H streams NMEA continuously, so
if no bytes arrive within ``probe_ms`` it raises ``DeviceNotFoundError``.

Example:
    from atgm336h import GPS, DeviceNotFoundError
    gps = GPS(bus_id=0, tx=0, rx=1)   # UART opened + probed here
    line = gps.readline()          # "$GPRMC,..." or None when no line is ready
"""

import utime

__all__ = ["GPS", "DeviceNotFoundError"]

# Default probe budget. The ATGM336H emits at least one sentence per second, so
# ~2 s reliably catches a wired module while staying short on a dead line.
_PROBE_MS = 2_000
_PROBE_POLL_MS = 10
_LINE_CHAR_TIMEOUT_MS = 10


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

        self._uart = UART(
            bus_id,
            baudrate=9600,
            tx=Pin(tx),
            rx=Pin(rx),
            timeout=0,
            timeout_char=_LINE_CHAR_TIMEOUT_MS,
        )
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
            The decoded sentence string (e.g. ``"$GPRMC,..."``), or ``None`` when
            no complete line is ready, the bytes cannot be decoded as ASCII, or
            the decoded line does not start with ``$``.
        """
        raw = self._uart.readline()
        if raw is None:
            return None
        try:
            line = raw.decode().strip()
        except (ValueError, UnicodeError):
            return None
        return line if line.startswith("$") else None
