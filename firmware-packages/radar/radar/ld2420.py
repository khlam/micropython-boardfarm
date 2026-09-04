"""Read presence and range reports from an HLK-LD2420 radar sensor.

The radar is commanded into energy mode during startup so its report format does
not depend on the mode the module was last left in, then it streams fixed 45-byte
reports. Framing, wakeups, and report selection are
`radar.stream.ReportStream`; this module declares the LD2420's framing and
supplies its startup command sequence and decoder.

The radar measures range only: one presence flag and one distance, with no
bearing and no speed.
"""

import utime
from micropython import const

from radar.stream import DeviceNotFoundError, ReportStream, Target, u16

__all__ = ["LD2420"]

# Command and report framing from the HLK-LD2420 serial command protocol. A
# command frame is header, two-byte length, two-byte command, payload, footer;
# the length counts the command word and the payload. An ACK echoes the command
# word with _ACK_FLAG set and follows it with a status word.
_COMMAND_HEADER = b"\xfd\xfc\xfb\xfa"
_COMMAND_FOOTER = b"\x04\x03\x02\x01"
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
_PRESENCE_AT = const(6)
_DISTANCE_AT = const(7)
_MM_PER_CM = const(10)

# Five expected reports is a generous budget for one command answer.
_ACK_TIMEOUT_MS = const(500)

# The radar tracks one target at a time, so it always fills the first slot.
_SLOT = const(1)


class LD2420(ReportStream):
    """Own an IRQ-driven UART connection to an LD2420 radar.

    ``tx`` connects to the radar's RX pin and ``rx`` to its OT1 pin. Call
    ``wait_ready()`` before reading reports; only one coroutine may wait on
    this driver at a time.
    """

    NAME = "LD2420"
    BAUDRATE = 115_200
    HEADER = b"\xf4\xf3\xf2\xf1"
    FOOTER = b"\xf8\xf7\xf6\xf5"
    REPORT_LEN = 45  # 4-byte header + 2-byte length + 35-byte body + 4-byte footer.
    # The radar reports about ten times per second. Allow five expected reports
    # during normal reads and two seconds for device detection during startup.
    STARTUP_TIMEOUT_MS = 2_000
    REPORT_TIMEOUT_MS = 500

    async def _prepare(self) -> None:
        """Force energy mode so the report format does not depend on history."""
        for command, payload in _CONFIGURATION:
            self._send_command(command, payload)
            await self._await_ack(command)

    def _decode(self, report: bytes | bytearray) -> tuple:
        """Convert a valid report into the detected target, if the radar saw one.

        The range lands in ``y_mm``, the forward axis. This radar measures no
        bearing, speed, or distance step, so those fields report zero.

        Args:
            report: One complete 45-byte energy-mode report.

        Returns:
            A one-element tuple, or an empty tuple when nobody was present.
        """
        if not report[_PRESENCE_AT]:
            return ()
        return (Target(_SLOT, 0, u16(report, _DISTANCE_AT) * _MM_PER_CM, 0, 0),)

    def _send_command(self, command: int, payload: bytes) -> None:
        """Write one command frame and discard bytes received before its ACK.

        The ACK buffer is created here, and rebound rather than trimmed in place
        below, because a MicroPython bytearray supports no slice deletion. Only
        the three startup command frames pay for that allocation; the report path
        keeps the preallocated buffers it inherits.
        """
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
            if not await self._wait_rx(started_ms, _ACK_TIMEOUT_MS):
                raise DeviceNotFoundError(f"no LD2420 ACK for command {command:#06x}")

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
        """Return and consume the status word of a complete ACK for ``command``.

        Args:
            command: Command word whose echo identifies the expected ACK.

        Returns:
            The status word, or ``None`` while no complete matching ACK has
            arrived.
        """
        buffer = self._ack_buffer
        echo = command | _ACK_FLAG
        start = buffer.find(_COMMAND_HEADER)
        while start >= 0:
            frame_end = _ack_frame_end(buffer, start)
            if frame_end is None:
                return None
            if u16(buffer, start + _ACK_ECHO_AT) == echo:
                status = u16(buffer, start + _ACK_STATUS_AT)
                self._ack_buffer = buffer[frame_end:]
                return status
            start = buffer.find(_COMMAND_HEADER, frame_end)
        return None


def _ack_frame_end(buffer: bytearray, start: int) -> int | None:
    """Return the offset past a complete, well-formed ACK frame at ``start``."""
    body_at = start + len(_COMMAND_HEADER) + 2
    if len(buffer) < body_at:
        return None
    length = u16(buffer, start + len(_COMMAND_HEADER))
    if length < _ACK_BODY_MINIMUM:
        return None
    end = body_at + length + len(_COMMAND_FOOTER)
    if len(buffer) < end:
        return None
    if buffer[end - len(_COMMAND_FOOTER) : end] != _COMMAND_FOOTER:
        return None
    return end
