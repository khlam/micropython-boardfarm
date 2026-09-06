"""A minimal ReportStream driver standing in for a real radar."""

from radar.stream import ReportStream

MARKER_AT = 4


class Stream(ReportStream):
    """One marker byte per report stands in for a decoded target."""

    NAME = "STREAM"
    BAUDRATE = 115_200
    HEADER = b"\xa0\xa1\xa2\xa3"
    FOOTER = b"\xf0\xf1"
    REPORT_LEN = 12
    # Milliseconds, so a test that waits one out finishes immediately.
    STARTUP_TIMEOUT_MS = 10
    REPORT_TIMEOUT_MS = 10

    def _decode(self, report: bytes | bytearray) -> tuple:
        """Return the marker byte, or nothing when it is zero.

        Args:
            report: One complete report.

        Returns:
            A one-element tuple, or an empty tuple for a marker of zero.
        """
        marker = report[MARKER_AT]
        return (marker,) if marker else ()


def build_report(marker: int = 1) -> bytes:
    """Assemble one report whose decoded value is ``marker``.

    Args:
        marker: Byte the fake decoder reports; zero means nobody.

    Returns:
        The encoded report frame.
    """
    padding = Stream.REPORT_LEN - len(Stream.HEADER) - len(Stream.FOOTER) - 1
    return Stream.HEADER + bytes((marker,)) + bytes(padding) + Stream.FOOTER
