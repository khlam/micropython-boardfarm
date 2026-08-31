"""Host tests for the LD2450 decoder: no framing, no async."""

from radar import Target
from radar.ld2450 import _decode_signed_magnitude


def test_decode_signed_magnitude_bit_set_is_positive():
    assert _decode_signed_magnitude(0x8000 | 100) == 100


def test_decode_signed_magnitude_bit_clear_is_negative():
    assert _decode_signed_magnitude(100) == -100


def test_decode_signed_magnitude_zero_with_bit_set_is_zero():
    assert _decode_signed_magnitude(0x8000) == 0


def test_decode_signed_magnitude_max_magnitude_is_negative():
    assert _decode_signed_magnitude(0x7FFF) == -32767


def test_decode_targets_all_empty_returns_empty_tuple(ld2450, build_ld2450_report):
    report = build_ld2450_report()
    assert ld2450._decode(report) == ()


def test_decode_targets_skips_raw_zero_slots(ld2450, build_ld2450_report):
    report = build_ld2450_report((100, 200, 0, 50))
    targets = ld2450._decode(report)
    assert len(targets) == 1


def test_decode_targets_slot_numbering_is_one_based(ld2450, build_ld2450_report):
    report = build_ld2450_report((100, 200, 0, 50))
    assert ld2450._decode(report)[0].slot == 1


def test_decode_targets_middle_slot_keeps_slot_two(ld2450, build_ld2450_report):
    report = build_ld2450_report(None, (10, 20, 0, 5), None)
    targets = ld2450._decode(report)
    assert len(targets) == 1
    assert targets[0].slot == 2


def test_decode_targets_three_targets(ld2450, build_ld2450_report):
    report = build_ld2450_report((1, 2, 3, 4), (5, 6, 7, 8), (9, 10, 11, 12))
    targets = ld2450._decode(report)
    assert len(targets) == 3
    assert [t.slot for t in targets] == [1, 2, 3]


def test_decode_targets_decodes_signed_fields(ld2450, build_ld2450_report):
    report = build_ld2450_report((-100, 200, -5, 30))
    target = ld2450._decode(report)[0]
    assert target == Target(1, -100, 200, -5, 30)


def test_decode_targets_positive_zero_bit_set_not_skipped(ld2450, build_ld2450_report):
    """A raw 0x8000 field (positive zero) is truthy, so its slot is kept."""
    report = build_ld2450_report((0, 0, 0, 0))
    targets = ld2450._decode(report)
    assert len(targets) == 1
    assert targets[0] == Target(1, 0, 0, 0, 0)
