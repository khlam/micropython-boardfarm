"""Host CPython tests for the raster timezone lookup against the committed dataset.

These run against the real ``_tzdata.py`` blob, so they double as a regression
guard on the generated grid. All math is pure integer; no fake hardware needed.
"""

from __future__ import annotations

import pytest

from tz_offset import _grid, _tzdata


def _tzid(lat: float, lon: float) -> str | None:
    idx = _grid.tz_index_for(lat, lon)
    return None if idx is None else _tzdata.TZIDS[idx]


@pytest.mark.parametrize(
    "lat,lon,expected",
    [
        (37.3875, -121.9724, "America/Los_Angeles"),  # San Jose (the clock test fix)
        (41.8781, -87.6298, "America/Chicago"),  # Chicago
        (40.7128, -74.0060, "America/New_York"),  # New York City
        (39.7392, -104.9903, "America/Denver"),  # Denver
        (33.4484, -112.0740, "America/Phoenix"),  # Phoenix (no-DST Arizona)
        (52.5200, 13.4050, "Europe/Berlin"),  # Berlin
        (27.7172, 85.3240, "Asia/Kathmandu"),  # Kathmandu (+5:45)
        (35.6762, 139.6503, "Asia/Tokyo"),  # Tokyo
        (-33.8688, 151.2093, "Australia/Sydney"),  # Sydney (southern DST)
    ],
)
def test_known_cities_resolve(lat: float, lon: float, expected: str) -> None:
    assert _tzid(lat, lon) == expected


def test_open_ocean_is_none() -> None:
    # Remote equatorial Pacific — the land-only dataset leaves it uncovered.
    assert _grid.tz_index_for(0.0, -150.0) is None


def test_longitude_wraps_dateline() -> None:
    # 181 deg E is the same meridian as 179 deg W; both index the same cell.
    assert _grid.tz_index_for(0.0, 181.0) == _grid.tz_index_for(0.0, -179.0)


def test_poles_clamp_in_range() -> None:
    # Extreme latitudes must not walk off the grid; they return a value or None.
    assert (
        _grid.tz_index_for(90.0, 0.0) in range(len(_tzdata.TZIDS))
        or _grid.tz_index_for(90.0, 0.0) is None
    )
    assert (
        _grid.tz_index_for(-90.0, 0.0) in range(len(_tzdata.TZIDS))
        or _grid.tz_index_for(-90.0, 0.0) is None
    )
