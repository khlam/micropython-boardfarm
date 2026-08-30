"""Host tests for LD2420 UART frame synchronization and resync-after-garbage."""

import machine

from ld2420.ld2420 import _REPORT_FOOTER, _REPORT_HEADER, _REPORT_LEN, Target


def test_report_split_across_chunks_is_rejoined(radar, build_report):
    report = build_report(distance_cm=100)
    mid = 20
    machine.feed_uart_bytes(report[:mid])
    radar._drain_uart()
    assert radar._take_latest_targets() is None

    machine.feed_uart_bytes(report[mid:])
    radar._drain_uart()
    assert radar._take_latest_targets() == (Target(1000),)


def test_two_reports_in_one_chunk_keeps_only_newest(radar, build_report):
    older = build_report(distance_cm=11)
    newer = build_report(distance_cm=22)
    machine.feed_uart_bytes(older + newer)
    radar._drain_uart()
    assert radar._take_latest_targets() == (Target(220),)


def test_leading_garbage_before_header_is_discarded(radar, build_report):
    machine.feed_uart_bytes(b"\x00\x01\x02" + build_report(distance_cm=50))
    radar._drain_uart()
    assert radar._take_latest_targets() == (Target(500),)


def test_bad_footer_resyncs_via_embedded_header(radar):
    embedded_at = 20
    candidate = (
        _REPORT_HEADER
        + bytes(embedded_at - len(_REPORT_HEADER))
        + _REPORT_HEADER
        + bytes(_REPORT_LEN - embedded_at - len(_REPORT_HEADER))
    )
    machine.feed_uart_bytes(candidate)
    radar._drain_uart()
    assert radar._take_latest_targets() is None  # bad footer, no report yet

    # The retained bytes start at the embedded header, so the report completes
    # once the remainder of a frame that long arrives.
    machine.feed_uart_bytes(bytes(embedded_at - len(_REPORT_FOOTER)) + _REPORT_FOOTER)
    radar._drain_uart()
    assert radar._take_latest_targets() == ()  # resync found the embedded header


def test_bad_footer_with_header_suffix_retains_partial(radar):
    suffix = _REPORT_HEADER[:3]
    candidate = _REPORT_HEADER + bytes(_REPORT_LEN - len(_REPORT_HEADER) - len(suffix)) + suffix
    machine.feed_uart_bytes(candidate)
    radar._drain_uart()
    assert radar._take_latest_targets() is None
    assert radar._candidate_len == len(suffix)  # "F4 F3 F2" retained as a header prefix

    completion = _REPORT_HEADER[3:] + bytes(_REPORT_LEN - 8) + _REPORT_FOOTER
    machine.feed_uart_bytes(completion)
    radar._drain_uart()
    assert radar._take_latest_targets() == ()


def test_false_start_header_byte_still_locks_on(radar, build_report):
    machine.feed_uart_bytes(_REPORT_HEADER[:1] + build_report(distance_cm=70))
    radar._drain_uart()
    assert radar._take_latest_targets() == (Target(700),)


def test_non_header_byte_mid_header_resets_candidate(radar):
    machine.feed_uart_bytes(_REPORT_HEADER[:2] + b"\x00")
    radar._drain_uart()
    assert radar._candidate_len == 0


def test_bad_footer_with_no_header_fragment_anywhere_resets_fully(radar):
    """No embedded header and no partial-suffix match at all: full reset."""
    machine.feed_uart_bytes(_REPORT_HEADER + bytes(_REPORT_LEN - len(_REPORT_HEADER)))
    radar._drain_uart()
    assert radar._take_latest_targets() is None
    assert radar._candidate_len == 0
