"""Host tests for the LD2450 decoder: no framing, no async."""

from collections.abc import Callable

import pytest

from radar import LD2450, Target
from radar.ld2450 import _decode_signed_magnitude


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (0x8000 | 100, 100),  # sign bit set is positive
        (100, -100),  # sign bit clear is negative
        (0x8000, 0),  # positive zero
        (0x7FFF, -32767),  # largest magnitude, negative
    ],
)
def test_decode_signed_magnitude(raw: int, expected: int):
    """A raw sign-magnitude u16 decodes to its signed value; a set top bit is positive.

    Args:
        raw: The u16 as the radar sends it.
        expected: The signed value it decodes to.
    """
    assert _decode_signed_magnitude(raw) == expected


def test_decode_targets_all_empty_returns_empty_tuple(
    ld2450: LD2450, build_ld2450_report: Callable[..., bytes]
):
    """A report with three empty slots decodes to no targets.

    Args:
        ld2450: The driver whose decoder is under test.
        build_ld2450_report: Encodes the report to decode.
    """
    report = build_ld2450_report()
    assert ld2450._decode(report) == ()


def test_decode_targets_skips_raw_zero_slots(
    ld2450: LD2450, build_ld2450_report: Callable[..., bytes]
):
    """All-zero slots are dropped and the one filled slot keeps its number.

    Args:
        ld2450: The driver whose decoder is under test.
        build_ld2450_report: Encodes the report to decode.
    """
    report = build_ld2450_report((100, 200, 0, 50))
    targets = ld2450._decode(report)
    assert len(targets) == 1
    assert targets[0].slot == 1  # slot numbering is one-based


def test_decode_targets_middle_slot_keeps_slot_two(
    ld2450: LD2450, build_ld2450_report: Callable[..., bytes]
):
    """A target in the middle slot decodes as slot 2, not renumbered to 1.

    Args:
        ld2450: The driver whose decoder is under test.
        build_ld2450_report: Encodes the report to decode.
    """
    report = build_ld2450_report(None, (10, 20, 0, 5), None)
    targets = ld2450._decode(report)
    assert len(targets) == 1
    assert targets[0].slot == 2


def test_decode_targets_three_targets(ld2450: LD2450, build_ld2450_report: Callable[..., bytes]):
    """Three filled slots decode to three targets in slot order.

    Args:
        ld2450: The driver whose decoder is under test.
        build_ld2450_report: Encodes the report to decode.
    """
    report = build_ld2450_report((1, 2, 3, 4), (5, 6, 7, 8), (9, 10, 11, 12))
    targets = ld2450._decode(report)
    assert len(targets) == 3
    assert [t.slot for t in targets] == [1, 2, 3]


def test_decode_targets_decodes_signed_fields(
    ld2450: LD2450, build_ld2450_report: Callable[..., bytes]
):
    """Negative x and speed decode with their sign.

    Args:
        ld2450: The driver whose decoder is under test.
        build_ld2450_report: Encodes the report to decode.
    """
    report = build_ld2450_report((-100, 200, -5, 30))
    target = ld2450._decode(report)[0]
    assert target == Target(1, -100, 200, -5, 30)


def test_decode_targets_positive_zero_bit_set_not_skipped(
    ld2450: LD2450, build_ld2450_report: Callable[..., bytes]
):
    """A raw 0x8000 field (positive zero) is truthy, so its slot is kept.

    Args:
        ld2450: The driver whose decoder is under test.
        build_ld2450_report: Encodes the report to decode.
    """
    report = build_ld2450_report((0, 0, 0, 0))
    targets = ld2450._decode(report)
    assert len(targets) == 1
    assert targets[0] == Target(1, 0, 0, 0, 0)
