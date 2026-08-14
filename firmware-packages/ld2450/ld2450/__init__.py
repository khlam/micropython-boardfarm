"""MicroPython driver for the HLK-LD2450 three-target radar stream.

The driver owns the radar UART, finds fixed-length report frames in an
arbitrary byte stream, and returns decoded target records. It intentionally
does not alter persistent radar configuration.
"""

from collections import namedtuple

import utime
from micropython import const

__all__ = ["LD2450", "DeviceNotFoundError", "Target"]

_BAUDRATE = const(256_000)
_FRAME_LEN = const(30)
_TARGET_LEN = const(8)
_TARGET_COUNT = const(3)
_POLL_MS = const(10)
_HEADER = b"\xaa\xff\x03\x00"
_TRAILER = b"\x55\xcc"

Target = namedtuple(
    "Target",
    ("slot", "x_mm", "y_mm", "speed_cm_s", "resolution_mm"),
)


class DeviceNotFoundError(Exception):
    """No valid LD2450 report frame arrived during the probe window."""


class LD2450:
    """Read target reports from an LD2450 connected to a driver-owned UART."""

    def __init__(
        self,
        *,
        bus_id: int,
        tx: int,
        rx: int,
        probe_ms: int = 2_000,
        frame_timeout_ms: int = 500,
    ) -> None:
        """Open the radar UART and confirm that valid reports are arriving.

        Args:
            bus_id: UART peripheral identifier.
            tx: GPIO number connected to the radar RX pin.
            rx: GPIO number connected to the radar TX pin.
            probe_ms: Maximum initial wait for a valid report frame.
            frame_timeout_ms: Maximum wait performed by each subsequent read.

        Raises:
            DeviceNotFoundError: If no valid report frame arrives while probing.
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
        self._frame_timeout_ms = frame_timeout_ms
        self._buffer = bytearray()
        self._pending = self._read_targets(probe_ms)
        if self._pending is None:
            raise DeviceNotFoundError(f"no valid LD2450 frame within {probe_ms} ms")

    def read(self) -> tuple | None:
        """Return targets from the next report, or ``None`` on frame timeout.

        The returned tuple preserves the radar's slot numbers. A valid report
        with no active targets returns an empty tuple; a timeout returns
        ``None``. UART errors propagate as ``OSError``.

        Returns:
            Zero to three ``Target`` records, or ``None`` on timeout.
        """
        if self._pending is not None:
            targets = self._pending
            self._pending = None
            return targets
        return self._read_targets(self._frame_timeout_ms)

    def read_latest(self) -> tuple | None:
        """Return targets from the freshest complete report available.

        Buffered older reports are discarded so a temporarily slow consumer
        catches up to the radar instead of replaying stale positions. If no
        complete report is buffered, this waits up to ``frame_timeout_ms``.

        Returns:
            Zero to three ``Target`` records, or ``None`` on timeout.
        """
        pending = self._pending
        self._pending = None

        chunk = self._uart.read()
        if chunk:
            self._buffer.extend(chunk)
        targets = self._extract_latest_targets()
        if targets is not None:
            return targets
        if pending is not None:
            return pending
        return self._read_latest_targets(self._frame_timeout_ms)

    def _read_targets(self, timeout_ms: int) -> tuple | None:
        """Wait up to ``timeout_ms`` for one complete report and decode it."""
        started_ms = utime.ticks_ms()
        while utime.ticks_diff(utime.ticks_ms(), started_ms) < timeout_ms:
            targets = self._extract_targets()
            if targets is not None:
                return targets

            chunk = self._uart.read()
            if chunk:
                self._buffer.extend(chunk)
                continue
            utime.sleep_ms(_POLL_MS)

        return self._extract_targets()

    def _read_latest_targets(self, timeout_ms: int) -> tuple | None:
        """Wait up to ``timeout_ms`` and return only the freshest report."""
        started_ms = utime.ticks_ms()
        while utime.ticks_diff(utime.ticks_ms(), started_ms) < timeout_ms:
            chunk = self._uart.read()
            if chunk:
                self._buffer.extend(chunk)
            targets = self._extract_latest_targets()
            if targets is not None:
                return targets
            utime.sleep_ms(_POLL_MS)

        chunk = self._uart.read()
        if chunk:
            self._buffer.extend(chunk)
        return self._extract_latest_targets()

    def _discard_prefix(self, count: int) -> None:
        """Drop consumed bytes using slicing supported by MicroPython bytearray."""
        self._buffer = self._buffer[count:]

    def _extract_targets(self) -> tuple | None:
        """Decode and remove the next valid report currently in the receive buffer."""
        while True:
            header_at = self._buffer.find(_HEADER)
            if header_at < 0:
                keep = min(len(self._buffer), len(_HEADER) - 1)
                discard = len(self._buffer) - keep
                if discard:
                    self._discard_prefix(discard)
                return None
            if header_at:
                self._discard_prefix(header_at)
            if len(self._buffer) < _FRAME_LEN:
                return None
            if self._buffer[_FRAME_LEN - len(_TRAILER) : _FRAME_LEN] != _TRAILER:
                self._discard_prefix(1)
                continue
            targets = _decode_targets(self._buffer)
            self._discard_prefix(_FRAME_LEN)
            return targets

    def _extract_latest_targets(self) -> tuple | None:
        """Decode all complete reports and return only the freshest one."""
        latest = None
        while True:
            targets = self._extract_targets()
            if targets is None:
                return latest
            latest = targets


def _decode_targets(frame: bytes | bytearray) -> tuple:
    """Decode the three target slots in a validated report frame."""
    targets = []
    for index in range(_TARGET_COUNT):
        start = len(_HEADER) + index * _TARGET_LEN
        x = _u16(frame, start)
        y = _u16(frame, start + 2)
        speed = _u16(frame, start + 4)
        resolution = _u16(frame, start + 6)
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
    """Decode one little-endian unsigned 16-bit value without allocating."""
    return data[offset] | data[offset + 1] << 8


def _decode_signed_magnitude(value: int) -> int:
    """Decode Hi-Link's bit-15-positive, bit-15-clear-negative representation."""
    magnitude = value & 0x7FFF
    return magnitude if value & 0x8000 else -magnitude
