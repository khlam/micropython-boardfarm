"""Convert GPS UTC date/time to DST-aware local time from latitude and longitude.

A point-in-polygon lookup over a frozen global timezone raster (``_grid`` plus the
generated ``_tzdata``) resolves the GPS fix to an IANA timezone, whose POSIX TZ
rule string (``_posix``) is evaluated against the current UTC date to produce the
correct offset — including daylight saving and sub-hour zones. Cells the raster
does not cover (open water) fall back to a longitude-derived whole-hour offset.

Everything here is pure integer math with no I/O, so the same code runs on the MCU
and under host CPython pytest. There is nothing chip-specific, so this package has
no per-chip backends.
"""

from tz_offset import _grid, _posix, _tzdata
from tz_offset._calendar import utc_to_local, utc_to_local_seconds, weekday

__all__ = (
    "local_from_gps",
    "offset_hours_from_longitude",
    "offset_seconds_from_gps",
    "utc_to_local",
    "utc_to_local_seconds",
    "weekday",
)

# round(lon/15) can reach ±13 near the date line; clamp to the real UTC range.
_MIN_OFFSET = -12
_MAX_OFFSET = 14


def offset_hours_from_longitude(lon: float) -> int:
    """Derive a whole-hour UTC offset from longitude (ocean / no-coverage fallback).

    Args:
        lon: Longitude in decimal degrees (east positive, west negative).

    Returns:
        ``round(lon / 15)`` clamped to ``[-12, 14]`` — used only where the timezone
        raster has no coverage (open water).
    """
    offset = round(lon / 15)
    if offset < _MIN_OFFSET:
        return _MIN_OFFSET
    if offset > _MAX_OFFSET:
        return _MAX_OFFSET
    return offset


def _parse_utc(date_str: str, utc_str: str) -> tuple:
    """Split GPS ``"YYYY-MM-DD"`` and ``"HH:MM:SSZ"`` strings into int fields."""
    return (
        int(date_str[0:4]),
        int(date_str[5:7]),
        int(date_str[8:10]),
        int(utc_str[0:2]),
        int(utc_str[3:5]),
        int(utc_str[6:8]),
    )


def offset_seconds_from_gps(date_str: str, utc_str: str, lat: float, lon: float) -> tuple:
    """Return ``(offset_seconds, abbrev)`` for a GPS fix.

    Looks up the timezone covering ``(lat, lon)`` and evaluates its POSIX TZ rule
    against the UTC instant. Falls back to a longitude-derived whole-hour offset
    (with ``abbrev`` ``None``) where the raster has no coverage.

    Args:
        date_str: GPS date as ``"YYYY-MM-DD"``.
        utc_str: GPS UTC time as ``"HH:MM:SSZ"`` (trailing ``Z`` tolerated).
        lat: Latitude in decimal degrees (north positive).
        lon: Longitude in decimal degrees (east positive).

    Returns:
        ``(offset_seconds, abbrev)``: the signed UTC->local offset in seconds and
        the zone abbreviation (e.g. ``"PDT"``), or ``None`` on the longitude
        fallback.
    """
    year, month, day, hour, minute, second = _parse_utc(date_str, utc_str)
    index = _grid.tz_index_for(lat, lon)
    if index is None:
        return (offset_hours_from_longitude(lon) * 3600, None)
    return _posix.offset_seconds(_tzdata.POSIX[index], year, month, day, hour, minute, second)


def local_from_gps(date_str: str, utc_str: str, lat: float, lon: float) -> tuple:
    """Build a DST-aware local date/time tuple from a GPS fix.

    Args:
        date_str: GPS date as ``"YYYY-MM-DD"`` (e.g. from ``nmea.parse_rmc``).
        utc_str: GPS UTC time as ``"HH:MM:SSZ"`` (trailing ``Z`` tolerated).
        lat: Latitude in decimal degrees (north positive).
        lon: Longitude in decimal degrees (east positive).

    Returns:
        ``(year, month, day, weekday, hour, minute, second)`` in local time, where
        ``weekday`` is 0=Monday..6=Sunday — ready to splice into a
        ``machine.RTC().datetime()`` tuple as ``local[:4] + local[4:7] + (0,)``.
    """
    year, month, day, hour, minute, second = _parse_utc(date_str, utc_str)
    offset_s, _abbrev = offset_seconds_from_gps(date_str, utc_str, lat, lon)
    local_year, local_month, local_day, local_hour, local_minute, local_second = (
        utc_to_local_seconds(year, month, day, hour, minute, second, offset_s)
    )
    return (
        local_year,
        local_month,
        local_day,
        weekday(local_year, local_month, local_day),
        local_hour,
        local_minute,
        local_second,
    )
