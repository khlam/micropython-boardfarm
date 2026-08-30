"""Read current target reports from an HLK-LD2450 radar sensor.

The radar sends ten 30-byte reports each second over a UART serial connection.
Framing, wakeups, and report selection are `radar.stream.ReportStream`; this
module declares the LD2450's framing and decodes its three target slots. The
driver reads data only and never changes the radar's settings.
"""

from micropython import const

from radar.stream import ReportStream, Target, u16

__all__ = ["LD2450"]

# The HLK-LD2450 serial protocol V1.03 calls each 30-byte report a data frame.
# This driver calls it a report. Sections 1.1 and 2.3 define these values.
_TARGET_LEN = const(8)  # x, y, speed, and resolution are each two bytes.
_TARGET_COUNT = const(3)


class LD2450(ReportStream):
    """Own an IRQ-driven UART connection to an LD2450 radar.

    ``tx`` connects to the radar's RX pin and ``rx`` to its TX pin. Call
    ``wait_ready()`` before reading reports; only one coroutine may wait on
    this driver at a time.
    """

    NAME = "LD2450"
    BAUDRATE = 256_000
    HEADER = b"\xaa\xff\x03\x00"
    FOOTER = b"\x55\xcc"
    REPORT_LEN = 30  # 4-byte header + three 8-byte targets + 2-byte trailer.
    # Section 2.3 specifies ten reports per second. Allow five expected reports
    # during normal reads and two seconds for device detection during startup.
    STARTUP_TIMEOUT_MS = 2_000
    REPORT_TIMEOUT_MS = 500

    def _decode(self, report: bytes | bytearray) -> tuple:
        """Convert the three slots in a valid report into active targets.

        Args:
            report: One complete 30-byte report.

        Returns:
            One :class:`Target` per slot the radar is tracking.
        """
        targets = []
        for index in range(_TARGET_COUNT):
            start = len(self.HEADER) + index * _TARGET_LEN
            x = u16(report, start)
            y = u16(report, start + 2)
            speed = u16(report, start + 4)
            resolution = u16(report, start + 6)
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


def _decode_signed_magnitude(value: int) -> int:
    """Convert the radar's sign-bit format to a positive or negative integer."""
    magnitude = value & 0x7FFF
    return magnitude if value & 0x8000 else -magnitude
