"""Host CPython tests for the shared pure-integer calendar primitives.

Focuses on the second-resolution ``utc_to_local_seconds`` (the whole-hour
``utc_to_local`` and ``weekday`` are covered through the public surface in
test_tz_offset.py). All functions are pure, so no fake hardware is needed.
"""

from __future__ import annotations

import pytest

from tz_offset import _calendar

# Whole-hour offsets the legacy helper already covers; the seconds helper must
# agree with it cell-for-cell when the offset is a whole number of hours.
_WHOLE_HOUR_CASES = [
    (2025, 6, 18, 10, 30, 15, 2),
    (2025, 6, 18, 12, 0, 0, -5),
    (2025, 6, 18, 23, 0, 0, 3),
    (2025, 6, 18, 1, 0, 0, -5),
    (2025, 6, 30, 23, 0, 0, 2),
    (2025, 7, 1, 0, 0, 0, -1),
    (2025, 12, 31, 23, 0, 0, 5),
    (2025, 1, 1, 0, 0, 0, -2),
    (2024, 2, 28, 23, 0, 0, 2),
    (2025, 2, 28, 23, 0, 0, 2),
    (2024, 3, 1, 0, 0, 0, -1),
    (2025, 6, 18, 2, 0, 0, 14),
    (2025, 6, 18, 22, 0, 0, -12),
]


@pytest.mark.parametrize("y,mo,d,h,mi,s,off_h", _WHOLE_HOUR_CASES)
def test_seconds_matches_whole_hour(
    y: int, mo: int, d: int, h: int, mi: int, s: int, off_h: int
) -> None:
    assert _calendar.utc_to_local_seconds(
        y, mo, d, h, mi, s, off_h * 3600
    ) == _calendar.utc_to_local(y, mo, d, h, mi, s, off_h)


def test_seconds_no_rollover() -> None:
    assert _calendar.utc_to_local_seconds(2025, 6, 18, 10, 30, 15, 7200) == (
        2025,
        6,
        18,
        12,
        30,
        15,
    )


def test_seconds_half_hour_zone() -> None:
    # India +5:30 (19800 s): 10:00:00 UTC -> 15:30:00.
    assert _calendar.utc_to_local_seconds(2025, 6, 18, 10, 0, 0, 19800) == (2025, 6, 18, 15, 30, 0)


def test_seconds_three_quarter_hour_zone() -> None:
    # Nepal +5:45 (20700 s): 23:50:00 UTC -> 05:35:00 next day.
    assert _calendar.utc_to_local_seconds(2025, 6, 18, 23, 50, 0, 20700) == (2025, 6, 19, 5, 35, 0)


def test_seconds_negative_sub_hour() -> None:
    # Marquesas -9:30 (-34200 s): 05:00:00 UTC -> 19:30:00 previous day.
    assert _calendar.utc_to_local_seconds(2025, 6, 18, 5, 0, 0, -34200) == (2025, 6, 17, 19, 30, 0)


def test_seconds_carries_minutes_and_seconds() -> None:
    # +90 s pushes seconds past the minute and minutes past the hour edge.
    assert _calendar.utc_to_local_seconds(2025, 6, 18, 10, 59, 30, 90) == (2025, 6, 18, 11, 1, 0)


def test_seconds_extreme_positive_offset_rolls_day() -> None:
    # +14 h (50400 s): 23:00:00 UTC -> 13:00:00 next day.
    assert _calendar.utc_to_local_seconds(2025, 6, 18, 23, 0, 0, 50400) == (2025, 6, 19, 13, 0, 0)


def test_seconds_extreme_negative_offset_borrows_day() -> None:
    # -12 h (-43200 s): 06:00:00 UTC -> 18:00:00 previous day.
    assert _calendar.utc_to_local_seconds(2025, 6, 18, 6, 0, 0, -43200) == (2025, 6, 17, 18, 0, 0)


def test_seconds_year_rollover_with_seconds() -> None:
    # New Year's Eve, +5h01m05s offset crossing into the next year.
    assert _calendar.utc_to_local_seconds(2025, 12, 31, 23, 0, 0, 5 * 3600 + 65) == (
        2026,
        1,
        1,
        4,
        1,
        5,
    )


def test_seconds_leap_day_forward() -> None:
    # 28 Feb 23:30 2024 + 1h -> 29 Feb (2024 is a leap year).
    assert _calendar.utc_to_local_seconds(2024, 2, 28, 23, 30, 0, 3600) == (2024, 2, 29, 0, 30, 0)


def test_seconds_non_leap_skips_feb29() -> None:
    # 28 Feb 23:30 2025 + 1h -> 1 Mar (2025 is not a leap year).
    assert _calendar.utc_to_local_seconds(2025, 2, 28, 23, 30, 0, 3600) == (2025, 3, 1, 0, 30, 0)


def test_days_round_trip() -> None:
    # _date_from_days is the exact inverse of _days_from_epoch across a leap span.
    for y, mo, d in ((1970, 1, 1), (2024, 2, 29), (2025, 12, 31), (2026, 6, 23)):
        assert _calendar._date_from_days(_calendar._days_from_epoch(y, mo, d)) == (y, mo, d)
