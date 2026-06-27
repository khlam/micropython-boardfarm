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

        # timeout=0 keeps every read non-blocking so a cooperative display loop
        # is never stalled on the 9600-baud stream. We deliberately do NOT use
        # UART.readline(): it reads byte-by-byte and applies the per-byte
        # first-char `timeout` to each one, so timeout=0 truncates a sentence on
        # the ~1 ms inter-character gap. Instead we drain whatever bytes are
        # buffered and reassemble complete lines in `_buf` ourselves.
        self._uart = UART(bus_id, baudrate=9600, tx=Pin(tx), rx=Pin(rx), timeout=0)
        self._buf = bytearray()
        self._probe(probe_ms)

    def _probe(self, probe_ms: int) -> None:
        """Wait for a first complete line; raise DeviceNotFoundError if none arrives.

        The leading sentence is discarded: attaching mid-stream usually catches a
        partial line, so dropping through the first newline resyncs to a boundary.
        """
        t_start = utime.ticks_ms()
        while utime.ticks_diff(utime.ticks_ms(), t_start) < probe_ms:
            self._drain()
            if self._take_line() is not None:
                return
            utime.sleep_ms(_PROBE_POLL_MS)
        raise DeviceNotFoundError(f"no NMEA bytes within {probe_ms} ms")

    def _drain(self) -> None:
        """Append all currently-buffered UART bytes to the line buffer (non-blocking)."""
        n = self._uart.any()
        if not n:
            return
        chunk = self._uart.read(n)
        if chunk:
            self._buf.extend(chunk)

    def _take_line(self) -> bytes | None:
        """Pop the next complete line (up to and including the newline), or None.

        The remainder is kept by reassigning a fresh slice rather than
        ``del self._buf[:n]``: MicroPython's ``bytearray`` does not support item
        deletion (``TypeError`` on the MCU), even though it works under the
        CPython host tests. Slicing + reassignment is supported on both.
        """
        nl = self._buf.find(b"\n")
        if nl < 0:
            return None
        end = nl + 1
        line = bytes(self._buf[:end])
        self._buf = self._buf[end:]
        return line

    def readline(self) -> str | None:
        """Read one complete NMEA sentence without blocking.

        Drains the UART into an internal buffer and returns the next complete
        line. Partial sentences stay buffered across calls and are completed when
        the remaining bytes arrive, so a sentence split across reads is never
        truncated.

        Returns:
            The decoded sentence string (e.g. ``"$GPRMC,..."``), or ``None`` when
            no complete line is buffered yet, the bytes cannot be decoded as
            ASCII, or the decoded line does not start with ``$``.
        """
        self._drain()
        raw = self._take_line()
        if raw is None:
            return None
        try:
            line = raw.decode().strip()
        except (ValueError, UnicodeError):
            return None
        return line if line.startswith("$") else None
