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
_MAX_BUFFER_LEN = const(120)
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

    def _read_targets(self, timeout_ms: int) -> tuple | None:
        """Wait up to ``timeout_ms`` for one complete report and decode it."""
        started_ms = utime.ticks_ms()
        while utime.ticks_diff(utime.ticks_ms(), started_ms) < timeout_ms:
            frame = self._extract_frame()
            if frame is not None:
                return _decode_targets(frame)

            available = self._uart.any()
            if available:
                chunk = self._uart.read(available)
                if chunk:
                    self._buffer.extend(chunk)
                    self._bound_buffer()
                    continue
            utime.sleep_ms(_POLL_MS)

        frame = self._extract_frame()
        return None if frame is None else _decode_targets(frame)

    def _bound_buffer(self) -> None:
        """Keep enough recent input for resynchronization without unbounded growth."""
        overflow = len(self._buffer) - _MAX_BUFFER_LEN
        if overflow > 0:
            del self._buffer[:overflow]

    def _extract_frame(self) -> bytes | None:
        """Remove and return the next valid frame currently in the receive buffer."""
        while True:
            header_at = self._buffer.find(_HEADER)
            if header_at < 0:
                keep = min(len(self._buffer), len(_HEADER) - 1)
                if keep:
                    del self._buffer[:-keep]
                else:
                    del self._buffer[:]
                return None
            if header_at:
                del self._buffer[:header_at]
            if len(self._buffer) < _FRAME_LEN:
                return None
            if self._buffer[_FRAME_LEN - len(_TRAILER) : _FRAME_LEN] != _TRAILER:
                del self._buffer[0]
                continue
            frame = bytes(self._buffer[:_FRAME_LEN])
            del self._buffer[:_FRAME_LEN]
            return frame


def _decode_targets(frame: bytes) -> tuple:
    """Decode the three target slots in a validated report frame."""
    targets = []
    for index in range(_TARGET_COUNT):
        start = len(_HEADER) + index * _TARGET_LEN
        slot_data = frame[start : start + _TARGET_LEN]
        if not any(slot_data):
            continue
        targets.append(
            Target(
                index + 1,
                _decode_signed_magnitude(_u16(slot_data, 0)),
                _decode_signed_magnitude(_u16(slot_data, 2)),
                _decode_signed_magnitude(_u16(slot_data, 4)),
                _u16(slot_data, 6),
            )
        )
    return tuple(targets)


def _u16(data: bytes, offset: int) -> int:
    """Decode one little-endian unsigned 16-bit value without allocating."""
    return data[offset] | data[offset + 1] << 8


def _decode_signed_magnitude(value: int) -> int:
    """Decode Hi-Link's bit-15-positive, bit-15-clear-negative representation."""
    magnitude = value & 0x7FFF
    return magnitude if value & 0x8000 else -magnitude
