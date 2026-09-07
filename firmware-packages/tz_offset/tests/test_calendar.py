"""Calendar conversion checked against an independent Gregorian implementation."""

from datetime import datetime, timedelta

import pytest

import tz_offset


@pytest.mark.parametrize(
    "utc,offset_hours",
    [
        ((2025, 6, 18, 10, 30, 15), 0),
        ((2025, 6, 18, 10, 30, 15), 2),
        ((2025, 6, 18, 12, 30, 15), -5),
        ((2025, 6, 18, 23, 30, 15), 14),
        ((2025, 6, 18, 1, 30, 15), -12),
        ((2025, 6, 30, 23, 30, 15), 2),
        ((2025, 7, 1, 0, 30, 15), -1),
        ((2025, 12, 31, 23, 30, 15), 5),
        ((2025, 1, 1, 0, 30, 15), -2),
        ((2024, 2, 28, 23, 30, 15), 2),
        ((2025, 2, 28, 23, 30, 15), 2),
        ((2024, 3, 1, 0, 30, 15), -1),
        ((2000, 2, 28, 23, 30, 15), 2),
        ((2100, 3, 1, 0, 30, 15), -1),
        ((2025, 12, 31, 23, 30, 15), 49),
        ((2025, 1, 1, 0, 30, 15), -49),
    ],
    ids=[
        "zero",
        "east",
        "west",
        "max_east",
        "max_west",
        "next_month",
        "previous_month",
        "next_year",
        "previous_year",
        "leap_day",
        "non_leap_day",
        "previous_leap_day",
        "leap_century",
        "non_leap_century",
        "multiple_days_forward",
        "multiple_days_backward",
    ],
)
def test_whole_hour_offsets_match_the_gregorian_calendar(utc, offset_hours):
    local = datetime(*utc) + timedelta(hours=offset_hours)
    expected = (local.year, local.month, local.day, local.hour, local.minute, local.second)
    assert tz_offset.utc_to_local_seconds(*utc, offset_hours * 3600) == expected


@pytest.mark.parametrize(
    "utc,offset_seconds,expected",
    [
        ((2025, 6, 18, 10, 0, 0), 19800, (2025, 6, 18, 15, 30, 0)),
        ((2025, 6, 18, 23, 50, 0), 20700, (2025, 6, 19, 5, 35, 0)),
        ((2025, 6, 18, 5, 0, 0), -34200, (2025, 6, 17, 19, 30, 0)),
        ((2025, 6, 18, 10, 59, 30), 90, (2025, 6, 18, 11, 1, 0)),
        ((2025, 1, 1, 0, 0, 0), -1, (2024, 12, 31, 23, 59, 59)),
        ((2024, 2, 29, 23, 59, 59), 1, (2024, 3, 1, 0, 0, 0)),
        ((1970, 1, 1, 0, 0, 0), 0, (1970, 1, 1, 0, 0, 0)),
    ],
    ids=["half_hour", "quarter_hour", "negative_fraction", "carry", "borrow", "leap_end", "epoch"],
)
def test_seconds_offset_preserves_sub_hour_precision(utc, offset_seconds, expected):
    assert tz_offset.utc_to_local_seconds(*utc, offset_seconds) == expected
