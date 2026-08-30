"""Read presence and range reports from an HLK-LD2420 radar sensor.

The radar is commanded into energy mode during startup so its report format does
not depend on the mode the module was last left in, then it streams fixed 45-byte
reports over a UART serial connection. An RX-idle interrupt wakes one asyncio
reader, which drains the UART and decodes only the newest complete valid report.

The radar measures range only: one presence flag and one distance, with no
bearing and no speed.
"""

import asyncio
from collections import namedtuple

import utime
from micropython import const

# Command and report framing from the HLK-LD2420 serial command protocol. A
# command frame is header, two-byte length, two-byte command, payload, footer;
# the length counts the command word and the payload. An ACK echoes the command
# word with _ACK_FLAG set and follows it with a status word.
_BAUDRATE = const(115_200)

_COMMAND_HEADER = b"\xfd\xfc\xfb\xfa"
_COMMAND_FOOTER = b"\x04\x03\x02\x01"
_REPORT_HEADER = b"\xf4\xf3\xf2\xf1"
_REPORT_FOOTER = b"\xf8\xf7\xf6\xf5"

_ENABLE_CONFIG = const(0x00FF)
_DISABLE_CONFIG = const(0x00FE)
_WRITE_SYSTEM_PARAM = const(0x0012)
_ACK_FLAG = const(0x0100)
_ACK_OK = const(0x0000)

# Enabling configuration carries the protocol version. Writing a system
# parameter carries the parameter word, its value, and a reserved word; system
# mode 0x0004 is the energy mode this driver decodes.
_CONFIGURATION = (
    (_ENABLE_CONFIG, b"\x01\x00"),
    (_WRITE_SYSTEM_PARAM, b"\x00\x00\x04\x00\x00\x00"),
    (_DISABLE_CONFIG, b""),
)

# Offsets from the start of an ACK frame, and the smallest body it can carry.
_ACK_ECHO_AT = const(6)
_ACK_STATUS_AT = const(8)
_ACK_BODY_MINIMUM = const(4)
_ACK_BUFFER_LIMIT = const(256)

# An energy-mode report is a presence byte, a two-byte distance in centimetres,
# and one two-byte energy value for each of the sixteen range gates.
_REPORT_LEN = const(45)  # 4-byte header + 2-byte length + 35-byte body + 4-byte footer.
_PRESENCE_AT = const(6)
_DISTANCE_AT = const(7)
_MM_PER_CM = const(10)

# A 512-byte UART ring holds about eleven reports at the documented rate. The
# drain buffer fits four whole reports and is reused for every UART read.
_UART_RX_BUFFER_LEN = const(512)
_DRAIN_BUFFER_LEN = const(180)

# The radar reports about ten times per second. Allow five expected reports
# during normal reads and two seconds for device detection during startup.
_ACK_TIMEOUT_MS = const(500)
_REPORT_TIMEOUT_MS = const(500)
_STARTUP_TIMEOUT_MS = const(2_000)

Target = namedtuple("Target", ("distance_mm",))


class DeviceNotFoundError(Exception):
    """The radar did not accept configuration or send a valid report."""


class LD2420:
    """Own an IRQ-driven UART connection to an LD2420 radar."""

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
            rx: GPIO number connected to the radar OT1 pin.
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
        # Rebound rather than trimmed in place, because a MicroPython bytearray
        # supports no slice deletion. Only the three startup command frames pay
        # for that allocation; the report path keeps its preallocated buffers.
        self._ack_buffer = bytearray()
        self._pending = None
        self._ready = False
        self._reading = False
        self._closed = False
        self._irq = self._uart.irq(
            handler=self._on_rx_idle,
            trigger=UART.IRQ_RXIDLE,
            hard=False,
        )

    async def wait_ready(self) -> None:
        """Select energy mode, then retain the first report for ``read_latest()``.

        Raises:
            DeviceNotFoundError: If the radar does not accept the configuration
                sequence or sends no valid report within two seconds.
            OSError: If the UART connection fails.
            RuntimeError: If the driver is closed or already has an active reader.
        """
        if self._closed:
            raise RuntimeError("LD2420 is closed")
        if self._ready:
            return

        self._claim_reader()
        try:
            await self._configure()
            targets = await self._wait_for_latest(_STARTUP_TIMEOUT_MS)
        except (DeviceNotFoundError, OSError):
            self.close()
            raise
        finally:
            self._reading = False

        if targets is None:
            self.close()
            raise DeviceNotFoundError(f"no valid LD2420 report within {_STARTUP_TIMEOUT_MS} ms")
        self._pending = targets
        self._ready = True

    async def read_latest(self) -> tuple | None:
        """Return the detected target from the newest available radar report.

        The UART is drained before returning, so older complete reports are
        validated but not decoded. An empty tuple means the newest report
        detected nobody. ``None`` means no complete report arrived within
        500 ms.

        Returns:
            A one-element tuple, an empty tuple, or ``None`` after a timeout.

        Raises:
            OSError: If reading the UART connection fails.
            RuntimeError: If startup is incomplete, the driver is closed, or
                another coroutine is reading.
        """
        if self._closed:
            raise RuntimeError("LD2420 is closed")
        if not self._ready:
            raise RuntimeError("call wait_ready() before read_latest()")

        self._claim_reader()
        try:
            self._drain_uart()
            targets = self._take_latest_targets()
            if targets is None:
                targets = self._pending
            self._pending = None
            if targets is not None:
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
            raise RuntimeError("LD2420 already has an active reader")
        self._reading = True

    def _on_rx_idle(self, _uart: object) -> None:
        """Wake the asyncio reader after the UART receive line becomes idle."""
        self._rx_ready.set()

    async def _configure(self) -> None:
        """Force energy mode so the report format does not depend on history."""
        for command, payload in _CONFIGURATION:
            self._send_command(command, payload)
            await self._await_ack(command)

    def _send_command(self, command: int, payload: bytes) -> None:
        """Write one command frame and discard bytes received before its ACK."""
        length = len(payload) + 2
        self._ack_buffer = bytearray()
        self._uart.write(
            _COMMAND_HEADER
            + bytes((length & 0xFF, length >> 8, command & 0xFF, command >> 8))
            + payload
            + _COMMAND_FOOTER
        )

    async def _await_ack(self, command: int) -> None:
        """Wait for a success ACK to ``command``.

        A malformed or missing ACK expires the timeout rather than being
        skipped, because a device that answers a command this way is not the
        radar this driver speaks to. A UART read failure propagates as OSError.

        Args:
            command: Command word whose echo identifies the expected ACK.

        Raises:
            DeviceNotFoundError: If the ACK reports a failure or never arrives.
        """
        started_ms = utime.ticks_ms()
        while True:
            self._drain_ack()
            status = self._take_ack_status(command)
            if status == _ACK_OK:
                return
            if status is not None:
                raise DeviceNotFoundError(f"LD2420 rejected command {command:#06x}: {status}")

            elapsed_ms = utime.ticks_diff(utime.ticks_ms(), started_ms)
            remaining_ms = _ACK_TIMEOUT_MS - elapsed_ms
            if remaining_ms <= 0:
                raise DeviceNotFoundError(f"no LD2420 ACK for command {command:#06x}")
            try:  # noqa: SIM105 - contextlib is not available on MicroPython
                await asyncio.wait_for_ms(self._rx_ready.wait(), remaining_ms)
            except asyncio.TimeoutError:  # noqa: UP041 - distinct on MicroPython.
                pass

    def _drain_ack(self) -> None:
        """Accumulate received bytes while a command ACK is outstanding."""
        while True:
            count = self._uart.readinto(self._drain_buffer)
            if not count:
                break
            self._ack_buffer += self._drain_buffer[:count]
        overflow = len(self._ack_buffer) - _ACK_BUFFER_LIMIT
        if overflow > 0:
            self._ack_buffer = self._ack_buffer[overflow:]

    def _take_ack_status(self, command: int) -> int | None:
        """Return and consume the status word of a complete ACK for ``command``."""
        buffer = self._ack_buffer
        echo = command | _ACK_FLAG
        start = buffer.find(_COMMAND_HEADER)
        while start >= 0:
            frame_end = _ack_frame_end(buffer, start)
            if frame_end is None:
                return None
            if _u16(buffer, start + _ACK_ECHO_AT) == echo:
                status = _u16(buffer, start + _ACK_STATUS_AT)
                self._ack_buffer = buffer[frame_end:]
                return status
            start = buffer.find(_COMMAND_HEADER, frame_end)
        return None

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
        """Read every available UART byte into the bounded report synchronizer."""
        while True:
            count = self._uart.readinto(self._drain_buffer)
            if not count:
                return
            for index in range(count):
                self._feed_byte(self._drain_buffer[index])

    def _feed_byte(self, value: int) -> None:
        """Advance report synchronization with one received byte."""
        if self._candidate_len < len(_REPORT_HEADER):
            if value == _REPORT_HEADER[self._candidate_len]:
                self._candidate[self._candidate_len] = value
                self._candidate_len += 1
            elif value == _REPORT_HEADER[0]:
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
        if self._candidate.endswith(_REPORT_FOOTER):
            self._candidate, self._latest_report = self._latest_report, self._candidate
            self._has_latest_report = True
            self._candidate_len = 0
            return
        self._resynchronize_candidate()

    def _resynchronize_candidate(self) -> None:
        """Retain an embedded header or partial header after a bad footer."""
        header_at = self._candidate.find(_REPORT_HEADER, 1)
        if header_at >= 0:
            retained = _REPORT_LEN - header_at
            for index in range(retained):
                self._candidate[index] = self._candidate[header_at + index]
            self._candidate_len = retained
            return

        for length in range(len(_REPORT_HEADER) - 1, 0, -1):
            if self._candidate.endswith(_REPORT_HEADER[:length]):
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


def _ack_frame_end(buffer: bytearray, start: int) -> int | None:
    """Return the offset past a complete, well-formed ACK frame at ``start``."""
    body_at = start + len(_COMMAND_HEADER) + 2
    if len(buffer) < body_at:
        return None
    length = _u16(buffer, start + len(_COMMAND_HEADER))
    if length < _ACK_BODY_MINIMUM:
        return None
    end = body_at + length + len(_COMMAND_FOOTER)
    if len(buffer) < end:
        return None
    if buffer[end - len(_COMMAND_FOOTER) : end] != _COMMAND_FOOTER:
        return None
    return end


def _decode_targets(report: bytes | bytearray) -> tuple:
    """Convert a valid report into the detected target, if the radar saw one."""
    if not report[_PRESENCE_AT]:
        return ()
    return (Target(_u16(report, _DISTANCE_AT) * _MM_PER_CM),)


def _u16(data: bytes | bytearray, offset: int) -> int:
    """Read a two-byte unsigned value stored with its low byte first."""
    return data[offset] | data[offset + 1] << 8
