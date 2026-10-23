"""Longitude-derived offsets and RTC weekday numbering."""

from datetime import date, timedelta

import pytest

import tz_offset


@pytest.mark.parametrize(
    "lon,expected",
    [
        (0.0, 0),
        (120.0, 8),
        (-75.0, -5),
        (7.49, 0),
        (7.51, 1),
        (-7.49, 0),
        (-7.51, -1),
        (180.0, 12),
        (-180.0, -12),
    ],
)
def test_longitude_rounds_to_the_nearest_15_degree_meridian(lon, expected):
    assert tz_offset.offset_hours_from_longitude(lon) == expected


@pytest.mark.parametrize(
    "lon,expected",
    [
        (195.0, 13),  # inside the range: 13 is a real offset, not clamped
        (210.0, 14),  # exactly the maximum, still unclamped
        (218.0, 14),  # round() gives 15; clamped down to the real UTC maximum
        (-180.0, -12),  # exactly the minimum, still unclamped
        (-195.0, -12),  # round() gives -13; clamped up to the real UTC minimum
    ],
)
def test_longitude_saturates_at_the_real_utc_offset_range(lon, expected):
    assert tz_offset.offset_hours_from_longitude(lon) == expected


@pytest.mark.parametrize("lon,expected", [(112.5, 8), (97.5, 6)], ids=["up", "down"])
def test_longitude_exactly_on_a_half_meridian_rounds_to_even(lon, expected):
    """A receiver sitting on a 7.5-degree boundary rounds to the *even* hour.

    ``round()`` is banker's rounding, so 112.5 goes up to 8 while 97.5 goes down
    to 6 — the tie does not consistently round away from zero. Pinned because the
    clock latches this offset for the whole run, and because MicroPython's
    ``round`` is not contractually required to break ties the same way CPython
    does; if the two ever diverge, this fails on the host first.
    """
    assert tz_offset.offset_hours_from_longitude(lon) == expected


@pytest.mark.parametrize(
    "day_offset", range(7), ids=["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
)
def test_weekday_numbers_every_day_from_monday_zero(day_offset):
    """Every weekday value the RTC can hold, against CPython's calendar."""
    day = date(2026, 6, 22) + timedelta(days=day_offset)

    assert tz_offset.weekday(day.year, day.month, day.day) == day_offset
    assert tz_offset.weekday(day.year, day.month, day.day) == day.weekday()


@pytest.mark.parametrize(
    "year,month,day",
    [(2024, 1, 1), (2024, 2, 29), (2000, 3, 1), (2100, 3, 1), (1970, 1, 1)],
    ids=["leap-year", "leap-day", "leap-century", "non-leap-century", "epoch"],
)
def test_weekday_spans_gregorian_century_rules(year, month, day):
    assert tz_offset.weekday(year, month, day) == date(year, month, day).weekday()
