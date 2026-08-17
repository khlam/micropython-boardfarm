"""Host tests for LD2450 UART frame synchronization and resync-after-garbage."""

import machine

from ld2450.ld2450 import _HEADER, _TRAILER, Target


def test_report_split_across_chunks_is_rejoined(radar, build_report):
    report = build_report((100, 200, 0, 50))
    mid = 10
    machine.feed_uart_bytes(report[:mid])
    radar._drain_uart()
    assert radar._take_latest_targets() is None

    machine.feed_uart_bytes(report[mid:])
    radar._drain_uart()
    targets = radar._take_latest_targets()
    assert targets == (Target(1, 100, 200, 0, 50),)


def test_two_reports_in_one_chunk_keeps_only_newest(radar, build_report):
    older = build_report((1, 1, 0, 1))
    newer = build_report((2, 2, 0, 2))
    machine.feed_uart_bytes(older + newer)
    radar._drain_uart()
    targets = radar._take_latest_targets()
    assert targets == (Target(1, 2, 2, 0, 2),)


def test_leading_garbage_before_header_is_discarded(radar, build_report):
    report = build_report((5, 5, 0, 5))
    machine.feed_uart_bytes(b"\x00\x01\x02" + report)
    radar._drain_uart()
    targets = radar._take_latest_targets()
    assert targets == (Target(1, 5, 5, 0, 5),)


def test_bad_trailer_resyncs_via_embedded_header(radar):
    candidate = _HEADER + (b"\x00" * 20) + _HEADER + b"\x00\x00"
    machine.feed_uart_bytes(candidate)
    radar._drain_uart()
    assert radar._take_latest_targets() is None  # bad trailer, no report yet

    completion = (b"\x00" * 22) + _TRAILER
    machine.feed_uart_bytes(completion)
    radar._drain_uart()
    assert radar._take_latest_targets() == ()  # resync found the embedded header


def test_bad_trailer_with_header_suffix_retains_partial(radar):
    candidate = _HEADER + (b"\x00" * 23) + b"\xaa\xff\x03"
    machine.feed_uart_bytes(candidate)
    radar._drain_uart()
    assert radar._take_latest_targets() is None
    assert radar._candidate_len == 3  # "AA FF 03" retained as a header prefix

    completion = b"\x00" + (b"\x00" * 24) + _TRAILER
    machine.feed_uart_bytes(completion)
    radar._drain_uart()
    assert radar._take_latest_targets() == ()


def test_false_start_header_bytes_still_lock_on(radar, build_report):
    report = build_report((7, 8, 0, 9))
    machine.feed_uart_bytes(b"\xaa" + report)
    radar._drain_uart()
    targets = radar._take_latest_targets()
    assert targets == (Target(1, 7, 8, 0, 9),)


def test_non_header_byte_mid_header_resets_candidate(radar):
    machine.feed_uart_bytes(b"\xaa\xff\x00")
    radar._drain_uart()
    assert radar._candidate_len == 0


def test_bad_trailer_with_no_header_fragment_anywhere_resets_fully(radar):
    """No embedded header and no partial-suffix match at all: full reset."""
    candidate = _HEADER + (b"\x00" * 24) + b"\x00\x00"
    machine.feed_uart_bytes(candidate)
    radar._drain_uart()
    assert radar._take_latest_targets() is None
    assert radar._candidate_len == 0
