"""Read current target reports from an HLK-LD2450 radar sensor.

The radar sends ten 30-byte reports each second over a UART serial connection.
An RX-idle interrupt wakes one asyncio reader, which drains the UART and decodes
only the newest complete valid report. The driver reads data only and never
changes the radar's settings.
"""

import asyncio
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

# A 512-byte UART ring holds about 1.7 seconds at the documented 300 bytes/s.
# The drain buffer fits four whole reports and is reused for every UART read.
_UART_RX_BUFFER_LEN = const(512)
_DRAIN_BUFFER_LEN = const(120)

# Section 2.3 specifies ten reports per second. Allow five expected reports
# during normal reads and two seconds for device detection during startup.
_REPORT_TIMEOUT_MS = const(500)
_STARTUP_TIMEOUT_MS = const(2_000)
_NO_PENDING = object()

Target = namedtuple(
    "Target",
    ("slot", "x_mm", "y_mm", "speed_cm_s", "resolution_mm"),
)


class DeviceNotFoundError(Exception):
    """The radar did not send a valid report during startup."""


class LD2450:
    """Own an IRQ-driven UART connection to an LD2450 radar."""

    def __init__(
        self,
        *,
        bus_id: int,
        tx: int,
        rx: int,
    ) -> None:
        """Open the radar UART and enable receive-idle wakeups.

        Call ``wait_ready()`` before reading reports. Only one coroutine may
        wait on this driver at a time.

        Args:
            bus_id: UART number used by the microcontroller.
            tx: GPIO number connected to the radar RX pin.
            rx: GPIO number connected to the radar TX pin.
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
            rxbuf=_UART_RX_BUFFER_LEN,
            timeout=0,
            timeout_char=0,
        )
        self._rx_ready = asyncio.ThreadSafeFlag()
        self._drain_buffer = bytearray(_DRAIN_BUFFER_LEN)
        self._candidate = bytearray(_REPORT_LEN)
        self._candidate_len = 0
        self._latest_report = bytearray(_REPORT_LEN)
        self._has_latest_report = False
        self._pending = _NO_PENDING
        self._ready = False
        self._reading = False
        self._closed = False
        self._irq = self._uart.irq(
            handler=self._on_rx_idle,
            trigger=UART.IRQ_RXIDLE,
            hard=False,
        )

    async def wait_ready(self) -> None:
        """Wait for the first valid report and retain it for ``read_latest()``.

        Raises:
            DeviceNotFoundError: If no valid report arrives within two seconds.
            OSError: If reading or closing the UART fails.
            RuntimeError: If the driver is closed or already has an active reader.
        """
        if self._closed:
            raise RuntimeError("LD2450 is closed")
        if self._ready:
            return

        self._claim_reader()
        try:
            targets = await self._wait_for_latest(_STARTUP_TIMEOUT_MS)
        except OSError:
            self.close()
            raise
        finally:
            self._reading = False

        if targets is None:
            self.close()
            raise DeviceNotFoundError(f"no valid LD2450 report within {_STARTUP_TIMEOUT_MS} ms")
        self._pending = targets
        self._ready = True

    async def read_latest(self) -> tuple | None:
        """Return active targets from the newest available radar report.

        The UART is drained before returning, so older complete reports are
        validated but not decoded. An empty tuple means the newest report has
        no active targets. ``None`` means no complete report arrived within
        500 ms.

        Returns:
            The active targets, an empty tuple, or ``None`` after a timeout.

        Raises:
            OSError: If reading the UART connection fails.
            RuntimeError: If startup is incomplete, the driver is closed, or
                another coroutine is reading.
        """
        if self._closed:
            raise RuntimeError("LD2450 is closed")
        if not self._ready:
            raise RuntimeError("call wait_ready() before read_latest()")

        self._claim_reader()
        try:
            self._drain_uart()
            targets = self._take_latest_targets()
            if targets is not None:
                self._pending = _NO_PENDING
                return targets
            if self._pending is not _NO_PENDING:
                targets = self._pending
                self._pending = _NO_PENDING
                return targets
            return await self._wait_for_latest(_REPORT_TIMEOUT_MS)
        except OSError:  # noqa: TRY203 - make the indirect UART failure contract explicit.
            raise
        finally:
            self._reading = False

    def close(self) -> None:
        """Disable receive wakeups and release the owned UART."""
        if self._closed:
            return
        self._closed = True
        try:
            self._uart.irq(handler=None)
            self._irq = None
        finally:
            self._uart.deinit()

    def _claim_reader(self) -> None:
        """Reserve the single IRQ flag waiter for the calling coroutine."""
        if self._reading:
            raise RuntimeError("LD2450 already has an active reader")
        self._reading = True

    def _on_rx_idle(self, _uart: object) -> None:
        """Wake the asyncio reader after the UART receive line becomes idle."""
        self._rx_ready.set()

    async def _wait_for_latest(self, timeout_ms: int) -> tuple | None:
        """Drain on each wake until a valid report arrives or time expires."""
        started_ms = utime.ticks_ms()
        while True:
            self._drain_uart()
            targets = self._take_latest_targets()
            if targets is not None:
                return targets

            elapsed_ms = utime.ticks_diff(utime.ticks_ms(), started_ms)
            remaining_ms = timeout_ms - elapsed_ms
            if remaining_ms <= 0:
                self._drain_uart()
                return self._take_latest_targets()

            try:
                await asyncio.wait_for_ms(self._rx_ready.wait(), remaining_ms)
            except asyncio.TimeoutError:  # noqa: UP041 - distinct on MicroPython.
                self._drain_uart()
                return self._take_latest_targets()

    def _drain_uart(self) -> None:
        """Read every available UART byte into the bounded frame synchronizer."""
        while True:
            count = self._uart.readinto(self._drain_buffer)
            if not count:
                return
            for index in range(count):
                self._feed_byte(self._drain_buffer[index])

    def _feed_byte(self, value: int) -> None:
        """Advance report synchronization with one received byte."""
        if self._candidate_len < len(_HEADER):
            if value == _HEADER[self._candidate_len]:
                self._candidate[self._candidate_len] = value
                self._candidate_len += 1
            elif value == _HEADER[0]:
                self._candidate[0] = value
                self._candidate_len = 1
            else:
                self._candidate_len = 0
            return

        self._candidate[self._candidate_len] = value
        self._candidate_len += 1
        if self._candidate_len == _REPORT_LEN:
            self._finish_candidate()

    def _finish_candidate(self) -> None:
        """Keep a valid report as newest or retain bytes useful for resync."""
        trailer_at = _REPORT_LEN - len(_TRAILER)
        if (
            self._candidate[trailer_at] == _TRAILER[0]
            and self._candidate[trailer_at + 1] == _TRAILER[1]
        ):
            self._candidate, self._latest_report = self._latest_report, self._candidate
            self._has_latest_report = True
            self._candidate_len = 0
            return
        self._resynchronize_candidate()

    def _resynchronize_candidate(self) -> None:
        """Retain an embedded header or partial header after a bad trailer."""
        header_at = self._candidate.find(_HEADER, 1)
        if header_at >= 0:
            retained = _REPORT_LEN - header_at
            for index in range(retained):
                self._candidate[index] = self._candidate[header_at + index]
            self._candidate_len = retained
            return

        for length in range(len(_HEADER) - 1, 0, -1):
            if self._candidate.endswith(_HEADER[:length]):
                suffix_at = _REPORT_LEN - length
                for index in range(length):
                    self._candidate[index] = self._candidate[suffix_at + index]
                self._candidate_len = length
                return
        self._candidate_len = 0

    def _take_latest_targets(self) -> tuple | None:
        """Decode and clear the newest valid raw report, if one is available."""
        if not self._has_latest_report:
            return None
        self._has_latest_report = False
        return _decode_targets(self._latest_report)


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
