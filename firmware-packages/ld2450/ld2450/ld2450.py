"""Read target reports from an HLK-LD2450 radar sensor.

The radar sends ten 30-byte reports each second over a UART serial connection.
Each report has three target slots. This driver collects the report bytes,
rejects invalid reports, and returns the active targets. It reads data only and
never changes the radar's settings.
"""

from collections import namedtuple

import utime
from micropython import const

# The HLK-LD2450 serial protocol V1.03 calls each 30-byte report a data frame.
# This driver calls it a report. Sections 1.1 and 2.3 define these values.
_BAUDRATE = const(256_000)
_REPORT_LEN = const(30)  # 4-byte header + three 8-byte targets + 2-byte trailer.
_TARGET_LEN = const(8)  # x, y, speed, and resolution are each two bytes.
_TARGET_COUNT = const(3)
_HEADER = b"\xaa\xff\x03\x00"
_TRAILER = b"\x55\xcc"

# Section 2.3 specifies ten reports per second. Check for bytes every 10 ms,
# wait for five expected reports during normal reads, and allow 2 s at startup.
_POLL_MS = const(10)
_REPORT_TIMEOUT_MS = const(500)
_STARTUP_TIMEOUT_MS = const(2_000)

Target = namedtuple(
    "Target",
    ("slot", "x_mm", "y_mm", "speed_cm_s", "resolution_mm"),
)


class DeviceNotFoundError(Exception):
    """The radar did not send a valid report during startup."""


class LD2450:
    """Read reports from an LD2450 connected directly to a UART."""

    def __init__(
        self,
        *,
        bus_id: int,
        tx: int,
        rx: int,
    ) -> None:
        """Open the radar connection and wait for its first valid report.

        Args:
            bus_id: UART number used by the microcontroller.
            tx: GPIO number connected to the radar RX pin.
            rx: GPIO number connected to the radar TX pin.

        Raises:
            DeviceNotFoundError: If no valid report arrives within two seconds.
        """
        from machine import UART, Pin  # noqa: PLC0415

        self._uart = UART(
            bus_id,
            baudrate=_BAUDRATE,
            bits=8,
            parity=None,
            stop=1,
            tx=Pin(tx),
            rx=Pin(rx),
            timeout=0,
            timeout_char=0,
        )
        self._buffer = bytearray()
        self._pending = self._poll(_STARTUP_TIMEOUT_MS, self._extract_targets)
        if self._pending is None:
            raise DeviceNotFoundError(f"no valid LD2450 report within {_STARTUP_TIMEOUT_MS} ms")

    def read(self) -> tuple | None:
        """Return the active targets from the next radar report.

        Each report has three numbered slots. Empty slots are left out, so the
        result contains zero to three ``Target`` records. ``None`` means that
        no complete report arrived within 500 ms.

        Returns:
            The active targets, an empty tuple, or ``None`` after a timeout.

        Raises:
            OSError: If reading the UART connection fails.
        """  # noqa: DOC502, RUF100 - UART.read() raises indirectly.
        if self._pending is not None:
            targets = self._pending
            self._pending = None
            return targets
        return self._poll(_REPORT_TIMEOUT_MS, self._extract_targets)

    def read_latest(self) -> tuple | None:
        """Return the active targets from the newest available radar report.

        If several complete reports have arrived, older reports are skipped so
        the returned positions are current. If no report is ready, this method
        waits up to 500 ms for one.

        Returns:
            The active targets, an empty tuple, or ``None`` after a timeout.

        Raises:
            OSError: If reading the UART connection fails.
        """  # noqa: DOC502, RUF100 - UART.read() raises indirectly.
        self._buffer.extend(self._uart.read() or b"")
        targets = self._extract_latest_targets()
        if targets is not None:
            self._pending = None
            return targets
        if self._pending is not None:
            pending = self._pending
            self._pending = None
            return pending
        return self._poll(_REPORT_TIMEOUT_MS, self._extract_latest_targets)

    def _poll(self, timeout_ms: int, extract: object) -> tuple | None:
        """Check the UART until a report is ready or the time limit is reached."""
        started_ms = utime.ticks_ms()
        while utime.ticks_diff(utime.ticks_ms(), started_ms) < timeout_ms:
            self._buffer.extend(self._uart.read() or b"")
            targets = extract()  # ty: ignore[call-non-callable]
            if targets is not None:
                return targets
            utime.sleep_ms(_POLL_MS)

        self._buffer.extend(self._uart.read() or b"")
        return extract()  # ty: ignore[call-non-callable]

    def _extract_targets(self) -> tuple | None:
        """Remove the next complete valid report and return its active targets."""
        while True:
            header_at = self._buffer.find(_HEADER)
            if header_at < 0:
                keep = min(len(self._buffer), len(_HEADER) - 1)
                discard = len(self._buffer) - keep
                if discard:
                    del self._buffer[:discard]
                return None
            if header_at:
                del self._buffer[:header_at]
            if len(self._buffer) < _REPORT_LEN:
                return None
            if self._buffer[_REPORT_LEN - len(_TRAILER) : _REPORT_LEN] != _TRAILER:
                del self._buffer[:1]
                continue
            targets = _decode_targets(self._buffer)
            del self._buffer[:_REPORT_LEN]
            return targets

    def _extract_latest_targets(self) -> tuple | None:
        """Read all complete reports and return active targets from the newest one."""
        latest = None
        while True:
            targets = self._extract_targets()
            if targets is None:
                return latest
            latest = targets


def _decode_targets(report: bytes | bytearray) -> tuple:
    """Convert the three slots in a valid report into active targets."""
    targets = []
    for index in range(_TARGET_COUNT):
        start = len(_HEADER) + index * _TARGET_LEN
        x = _u16(report, start)
        y = _u16(report, start + 2)
        speed = _u16(report, start + 4)
        resolution = _u16(report, start + 6)
        if not (x or y or speed or resolution):
            continue
        targets.append(
            Target(
                index + 1,
                _decode_signed_magnitude(x),
                _decode_signed_magnitude(y),
                _decode_signed_magnitude(speed),
                resolution,
            )
        )
    return tuple(targets)


def _u16(data: bytes | bytearray, offset: int) -> int:
    """Read a two-byte unsigned value stored with its low byte first."""
    return data[offset] | data[offset + 1] << 8


def _decode_signed_magnitude(value: int) -> int:
    """Convert the radar's sign-bit format to a positive or negative integer."""
    magnitude = value & 0x7FFF
    return magnitude if value & 0x8000 else -magnitude
