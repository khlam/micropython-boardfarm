"""Host CPython tests for the longitude-derived timezone offset logic.

All functions are pure, so tests import tz_offset directly — no fake hardware.
"""

from __future__ import annotations

import pytest

import tz_offset

# ---------------------------------------------------------------------------
# offset_hours_from_longitude
# ---------------------------------------------------------------------------


# Half-boundary longitudes (lon/15 == n.5) are avoided: round() rounds halves
# to even, which is confusing and varies by implementation.
@pytest.mark.parametrize(
    "lon,expected",
    [
        (0.0, 0),  # Greenwich
        (15.0, 1),
        (-15.0, -1),
        (120.0, 8),  # Beijing-ish
        (-75.0, -5),  # US Eastern-ish
        (8.0, 1),  # 0.53 rounds up
        (-7.0, 0),  # -0.47 rounds toward zero
        (180.0, 12),  # eastern edge of valid longitude
        (-180.0, -12),  # western edge
        (220.0, 14),  # out-of-range: 14.67 -> clamp ceiling +14
        (-190.0, -12),  # out-of-range: -12.67 -> clamp floor -12
    ],
)
def test_offset_hours_from_longitude(lon: float, expected: int) -> None:
    assert tz_offset.offset_hours_from_longitude(lon) == expected


# ---------------------------------------------------------------------------
# weekday  (0=Monday .. 6=Sunday)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "year,month,day,expected",
    [
        (2024, 1, 1, 0),  # Monday
        (2025, 6, 18, 2),  # Wednesday
        (2000, 1, 1, 5),  # Saturday
        (2025, 1, 1, 2),  # Wednesday
        (2024, 2, 29, 3),  # leap day, Thursday
        (1999, 12, 31, 4),  # Friday
        (2025, 6, 22, 6),  # Sunday
    ],
)
def test_weekday(year: int, month: int, day: int, expected: int) -> None:
    assert tz_offset.weekday(year, month, day) == expected


# ---------------------------------------------------------------------------
# utc_to_local  — offset application + rollover
# ---------------------------------------------------------------------------


def test_utc_to_local_no_rollover() -> None:
    assert tz_offset.utc_to_local(2025, 6, 18, 10, 30, 15, 2) == (2025, 6, 18, 12, 30, 15)


def test_utc_to_local_negative_no_rollover() -> None:
    assert tz_offset.utc_to_local(2025, 6, 18, 12, 0, 0, -5) == (2025, 6, 18, 7, 0, 0)


def test_utc_to_local_forward_across_midnight() -> None:
    # 23:00 UTC + 3h -> 02:00 next day.
    assert tz_offset.utc_to_local(2025, 6, 18, 23, 0, 0, 3) == (2025, 6, 19, 2, 0, 0)


def test_utc_to_local_backward_across_midnight() -> None:
    # 01:00 UTC - 5h -> 20:00 previous day.
    assert tz_offset.utc_to_local(2025, 6, 18, 1, 0, 0, -5) == (2025, 6, 17, 20, 0, 0)


def test_utc_to_local_month_rollover_forward() -> None:
    # 30 June 23:00 + 2h -> 1 July.
    assert tz_offset.utc_to_local(2025, 6, 30, 23, 0, 0, 2) == (2025, 7, 1, 1, 0, 0)


def test_utc_to_local_month_borrow_backward() -> None:
    # 1 July 00:00 - 1h -> 30 June 23:00.
    assert tz_offset.utc_to_local(2025, 7, 1, 0, 0, 0, -1) == (2025, 6, 30, 23, 0, 0)


def test_utc_to_local_year_rollover_forward() -> None:
    assert tz_offset.utc_to_local(2025, 12, 31, 23, 0, 0, 5) == (2026, 1, 1, 4, 0, 0)


def test_utc_to_local_year_borrow_backward() -> None:
    assert tz_offset.utc_to_local(2025, 1, 1, 0, 0, 0, -2) == (2024, 12, 31, 22, 0, 0)


def test_utc_to_local_leap_day_forward() -> None:
    # 28 Feb 23:00 2024 + 2h -> 29 Feb (2024 is a leap year).
    assert tz_offset.utc_to_local(2024, 2, 28, 23, 0, 0, 2) == (2024, 2, 29, 1, 0, 0)


def test_utc_to_local_non_leap_skips_feb29() -> None:
    # 28 Feb 23:00 2025 + 2h -> 1 Mar (2025 is not a leap year).
    assert tz_offset.utc_to_local(2025, 2, 28, 23, 0, 0, 2) == (2025, 3, 1, 1, 0, 0)


def test_utc_to_local_leap_day_borrow() -> None:
    # 1 Mar 00:00 2024 - 1h -> 29 Feb 2024.
    assert tz_offset.utc_to_local(2024, 3, 1, 0, 0, 0, -1) == (2024, 2, 29, 23, 0, 0)


# ---------------------------------------------------------------------------
# local_from_gps  — end-to-end
# ---------------------------------------------------------------------------


def test_local_from_gps_applies_dst_offset_and_weekday() -> None:
    # Berlin (CEST = +2h in June). 10:30:15 UTC Wed stays Wed (weekday 2).
    result = tz_offset.local_from_gps("2025-06-18", "10:30:15Z", 52.52, 13.405)
    assert result == (2025, 6, 18, 2, 12, 30, 15)


def test_local_from_gps_rolls_date_and_weekday_forward() -> None:
    # Sydney (AEST = +10h, winter in June). 23:30 UTC Wed -> 09:30 Thu (weekday 3).
    result = tz_offset.local_from_gps("2025-06-18", "23:30:00Z", -33.8688, 151.2093)
    assert result == (2025, 6, 19, 3, 9, 30, 0)


def test_local_from_gps_rolls_date_and_weekday_backward() -> None:
    # San Jose (PDT = -7h in June). 02:00:30 UTC Wed -> 19:00:30 Tue (weekday 1).
    result = tz_offset.local_from_gps("2025-06-18", "02:00:30Z", 37.3875, -121.9724)
    assert result == (2025, 6, 17, 1, 19, 0, 30)


# ---------------------------------------------------------------------------
# offset_seconds_from_gps  — DST-aware offset + abbreviation, ocean fallback
# ---------------------------------------------------------------------------


def test_offset_seconds_from_gps_returns_dst_offset_and_abbrev() -> None:
    # San Jose in June -> PDT, UTC-7.
    result = tz_offset.offset_seconds_from_gps("2026-06-23", "23:59:58Z", 37.3875, -121.9724)
    assert result == (-25200, "PDT")


def test_offset_seconds_from_gps_winter_standard_time() -> None:
    # San Jose in January -> PST, UTC-8.
    result = tz_offset.offset_seconds_from_gps("2026-01-15", "12:00:00Z", 37.3875, -121.9724)
    assert result == (-28800, "PST")


def test_offset_seconds_from_gps_ocean_falls_back_to_longitude() -> None:
    # Remote Pacific -> no raster coverage -> longitude offset, no abbreviation.
    # lon -150 -> round(-150/15) = -10h.
    result = tz_offset.offset_seconds_from_gps("2026-06-23", "12:00:00Z", 0.0, -150.0)
    assert result == (-36000, None)


def test_local_from_gps_ocean_uses_longitude_fallback() -> None:
    # Same remote Pacific point: -10h applied, no DST. 2026-06-23 is a Tuesday.
    result = tz_offset.local_from_gps("2026-06-23", "12:00:00Z", 0.0, -150.0)
    assert result == (2026, 6, 23, 1, 2, 0, 0)
