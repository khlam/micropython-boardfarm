"""Host tests for UART frame synchronization and resync-after-garbage."""

import machine
from fake_stream import Stream, build_report

HEADER = Stream.HEADER
FOOTER = Stream.FOOTER
REPORT_LEN = Stream.REPORT_LEN


def test_report_split_across_chunks_is_rejoined(stream):
    report = build_report(7)
    machine.feed_uart_bytes(report[:5])
    stream._drain_uart()
    assert stream._take_latest_targets() is None

    machine.feed_uart_bytes(report[5:])
    stream._drain_uart()
    assert stream._take_latest_targets() == (7,)


def test_two_reports_in_one_chunk_keeps_only_newest(stream):
    machine.feed_uart_bytes(build_report(1) + build_report(2))
    stream._drain_uart()
    assert stream._take_latest_targets() == (2,)


def test_leading_garbage_before_header_is_discarded(stream):
    machine.feed_uart_bytes(b"\x00\x01\x02" + build_report(5))
    stream._drain_uart()
    assert stream._take_latest_targets() == (5,)


def test_false_start_header_byte_still_locks_on(stream):
    machine.feed_uart_bytes(HEADER[:1] + build_report(9))
    stream._drain_uart()
    assert stream._take_latest_targets() == (9,)


def test_non_header_byte_mid_header_resets_candidate(stream):
    machine.feed_uart_bytes(HEADER[:2] + b"\x00")
    stream._drain_uart()
    assert stream._candidate_len == 0


def test_bad_footer_resyncs_via_embedded_header(stream):
    embedded_at = 6
    machine.feed_uart_bytes(
        HEADER
        + bytes(embedded_at - len(HEADER))
        + HEADER
        + bytes(REPORT_LEN - embedded_at - len(HEADER))
    )
    stream._drain_uart()
    assert stream._take_latest_targets() is None  # bad footer, no report yet

    # The retained bytes start at the embedded header, so the report completes
    # once the remainder of a frame that long arrives.
    machine.feed_uart_bytes(bytes(embedded_at - len(FOOTER)) + FOOTER)
    stream._drain_uart()
    assert stream._take_latest_targets() == ()  # resync found the embedded header


def test_bad_footer_with_header_suffix_retains_partial(stream):
    suffix = HEADER[:3]
    machine.feed_uart_bytes(HEADER + bytes(REPORT_LEN - len(HEADER) - len(suffix)) + suffix)
    stream._drain_uart()
    assert stream._take_latest_targets() is None
    assert stream._candidate_len == len(suffix)  # retained as a header prefix

    machine.feed_uart_bytes(HEADER[3:] + bytes(REPORT_LEN - len(HEADER) - len(FOOTER)) + FOOTER)
    stream._drain_uart()
    assert stream._take_latest_targets() == ()


def test_bad_footer_with_no_header_fragment_anywhere_resets_fully(stream):
    """No embedded header and no partial-suffix match at all: full reset."""
    machine.feed_uart_bytes(HEADER + bytes(REPORT_LEN - len(HEADER)))
    stream._drain_uart()
    assert stream._take_latest_targets() is None
    assert stream._candidate_len == 0
