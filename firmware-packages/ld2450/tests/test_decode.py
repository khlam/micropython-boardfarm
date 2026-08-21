"""Host tests for the LD2450 pure decode functions: no UART, no async."""

from ld2450.ld2450 import Target, _decode_signed_magnitude, _decode_targets, _u16


def test_decode_signed_magnitude_bit_set_is_positive():
    assert _decode_signed_magnitude(0x8000 | 100) == 100


def test_decode_signed_magnitude_bit_clear_is_negative():
    assert _decode_signed_magnitude(100) == -100


def test_decode_signed_magnitude_zero_with_bit_set_is_zero():
    assert _decode_signed_magnitude(0x8000) == 0


def test_decode_signed_magnitude_max_magnitude_is_negative():
    assert _decode_signed_magnitude(0x7FFF) == -32767


def test_u16_little_endian():
    assert _u16(bytes([0x34, 0x12]), 0) == 0x1234


def test_decode_targets_all_empty_returns_empty_tuple(build_report):
    report = build_report()
    assert _decode_targets(report) == ()


def test_decode_targets_skips_raw_zero_slots(build_report):
    report = build_report((100, 200, 0, 50))
    targets = _decode_targets(report)
    assert len(targets) == 1


def test_decode_targets_slot_numbering_is_one_based(build_report):
    report = build_report((100, 200, 0, 50))
    assert _decode_targets(report)[0].slot == 1


def test_decode_targets_middle_slot_keeps_slot_two(build_report):
    report = build_report(None, (10, 20, 0, 5), None)
    targets = _decode_targets(report)
    assert len(targets) == 1
    assert targets[0].slot == 2


def test_decode_targets_three_targets(build_report):
    report = build_report((1, 2, 3, 4), (5, 6, 7, 8), (9, 10, 11, 12))
    targets = _decode_targets(report)
    assert len(targets) == 3
    assert [t.slot for t in targets] == [1, 2, 3]


def test_decode_targets_decodes_signed_fields(build_report):
    report = build_report((-100, 200, -5, 30))
    target = _decode_targets(report)[0]
    assert target == Target(1, -100, 200, -5, 30)


def test_decode_targets_skips_positive_zero_fields(build_report):
    report = build_report((0, 0, 0, 0))
    assert _decode_targets(report) == ()
