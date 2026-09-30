"""Host tests for UART frame synchronization, resync-after-garbage, and field reads."""

import asyncio
from collections.abc import Callable

import machine
import pytest
from fake_stream import Stream, build_report

from radar.stream import u16

HEADER = Stream.HEADER
FOOTER = Stream.FOOTER
REPORT_LEN = Stream.REPORT_LEN


def test_report_split_across_chunks_is_rejoined(read_report: Callable[[], tuple | None]):
    """A report split across two UART chunks is read once its second half arrives.

    Args:
        read_report: Reads the newest report, or None when none is complete.
    """
    report = build_report(7)
    machine.feed_uart_bytes(report[:5])
    assert read_report() is None

    machine.feed_uart_bytes(report[5:])
    assert read_report() == (7,)


def test_two_reports_in_one_chunk_keeps_only_newest(read_report: Callable[[], tuple | None]):
    """Of two reports arriving in one chunk, only the newer is read.

    Args:
        read_report: Reads the newest report, or None when none is complete.
    """
    machine.feed_uart_bytes(build_report(1) + build_report(2))
    assert read_report() == (2,)


def test_leading_garbage_before_header_is_discarded(read_report: Callable[[], tuple | None]):
    """Bytes before a header are dropped and the report after them still reads.

    Args:
        read_report: Reads the newest report, or None when none is complete.
    """
    machine.feed_uart_bytes(b"\x00\x01\x02" + build_report(5))
    assert read_report() == (5,)


def test_false_start_header_byte_still_locks_on(read_report: Callable[[], tuple | None]):
    """A lone header byte right before a full report doesn't stop the report reading.

    Args:
        read_report: Reads the newest report, or None when none is complete.
    """
    machine.feed_uart_bytes(HEADER[:1] + build_report(9))
    assert read_report() == (9,)


def test_non_header_byte_mid_header_resets_candidate(
    stream: Stream, read_report: Callable[[], tuple | None]
):
    """A byte breaking a partial header discards the partial header.

    Args:
        stream: The stream whose candidate buffer is inspected.
        read_report: Reads the newest report, or None when none is complete.
    """
    machine.feed_uart_bytes(HEADER[:2] + b"\x00")
    assert read_report() is None
    assert stream._candidate_len == 0


def test_bad_footer_resyncs_via_embedded_header(read_report: Callable[[], tuple | None]):
    """A frame with a bad footer resyncs on a header embedded inside it.

    Args:
        read_report: Reads the newest report, or None when none is complete.
    """
    embedded_at = 6
    machine.feed_uart_bytes(
        HEADER
        + bytes(embedded_at - len(HEADER))
        + HEADER
        + bytes(REPORT_LEN - embedded_at - len(HEADER))
    )
    assert read_report() is None  # bad footer, no report yet

    # The retained bytes start at the embedded header, so the report completes
    # once the remainder of a frame that long arrives.
    machine.feed_uart_bytes(bytes(embedded_at - len(FOOTER)) + FOOTER)
    assert read_report() == ()  # resync found the embedded header


def test_bad_footer_with_header_suffix_retains_partial(
    stream: Stream, read_report: Callable[[], tuple | None]
):
    """A frame with a bad footer keeps a trailing header prefix for the next frame.

    Args:
        stream: The stream whose candidate buffer is inspected.
        read_report: Reads the newest report, or None when none is complete.
    """
    suffix = HEADER[:3]
    machine.feed_uart_bytes(HEADER + bytes(REPORT_LEN - len(HEADER) - len(suffix)) + suffix)
    assert read_report() is None
    assert stream._candidate_len == len(suffix)  # retained as a header prefix

    machine.feed_uart_bytes(HEADER[3:] + bytes(REPORT_LEN - len(HEADER) - len(FOOTER)) + FOOTER)
    assert read_report() == ()


def test_bad_footer_with_no_header_fragment_anywhere_resets_fully(
    stream: Stream, read_report: Callable[[], tuple | None]
):
    """No embedded header and no partial-suffix match at all: full reset.

    Args:
        stream: The stream whose candidate buffer is inspected.
        read_report: Reads the newest report, or None when none is complete.
    """
    machine.feed_uart_bytes(HEADER + bytes(REPORT_LEN - len(HEADER)))
    assert read_report() is None
    assert stream._candidate_len == 0


def test_u16_reads_a_little_endian_field():
    """u16() reads two bytes at an offset as a little-endian unsigned integer."""
    assert u16(bytes([0x34, 0x12]), 0) == 0x1234


@pytest.fixture
def read_report(stream: Stream) -> Callable[[], tuple | None]:
    """Read through the public interface after consuming its startup report.

    Args:
        stream: The stream to read from.

    Returns:
        A reader returning the newest report, or None when none is complete.
    """
    machine.feed_uart_bytes(build_report())
    asyncio.run(stream.wait_ready())
    asyncio.run(stream.read_latest())
    return lambda: asyncio.run(stream.read_latest())
