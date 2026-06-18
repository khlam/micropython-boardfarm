"""Convert GPS UTC date/time to local time using a longitude-derived UTC offset.

MicroPython has no timezone database, so local time is approximated from a fixed
whole-hour offset: ``round(longitude / 15)``. This ignores political timezone
boundaries and DST, but needs no lookup table and is good enough for a wall clock
that already knows its position from the GPS fix.

Everything here is pure integer/float math with no I/O, so the same code runs on
the MCU and under host CPython pytest. There is nothing chip-specific, so this
package has no per-chip backends.
"""

# round(lon/15) can reach ±13 near the date line; clamp to the real UTC range.
_MIN_OFFSET = -12
_MAX_OFFSET = 14

_DAYS_IN_MONTH = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)


def _is_leap(year: int) -> bool:
    """Return True when ``year`` is a Gregorian leap year."""
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def _days_in_month(year: int, month: int) -> int:
    """Return the number of days in ``month`` (1-12) of ``year``."""
    if month == 2 and _is_leap(year):
        return 29
    return _DAYS_IN_MONTH[month - 1]


def offset_hours_from_longitude(lon: float) -> int:
    """Derive a whole-hour UTC offset from longitude.

    Args:
        lon: Longitude in decimal degrees (east positive, west negative).

    Returns:
        ``round(lon / 15)`` clamped to ``[-12, 14]`` — the span of real-world
        UTC offsets.
    """
    offset = round(lon / 15)
    if offset < _MIN_OFFSET:
        return _MIN_OFFSET
    if offset > _MAX_OFFSET:
        return _MAX_OFFSET
    return offset


def weekday(year: int, month: int, day: int) -> int:
    """Return the day of week for a Gregorian date via Sakamoto's algorithm.

    Args:
        year: Four-digit year.
        month: Month, 1-12.
        day: Day of month, 1-31.

    Returns:
        ``0`` for Monday through ``6`` for Sunday, matching the weekday field
        of MicroPython's ``machine.RTC().datetime()`` on the rp2 port.
    """
    t = (0, 3, 2, 5, 0, 3, 5, 1, 4, 6, 2, 4)
    y = year - (1 if month < 3 else 0)
    # Sakamoto yields 0=Sunday..6=Saturday; rotate to 0=Monday..6=Sunday.
    sun0 = (y + y // 4 - y // 100 + y // 400 + t[month - 1] + day) % 7
    return (sun0 + 6) % 7


def utc_to_local(
    year: int,
    month: int,
    day: int,
    hour: int,
    minute: int,
    second: int,
    offset_hours: int,
) -> tuple:
    """Apply a whole-hour offset to a UTC date/time, rolling over date fields.

    Args:
        year: Four-digit UTC year.
        month: UTC month, 1-12.
        day: UTC day of month.
        hour: UTC hour, 0-23.
        minute: UTC minute, 0-59.
        second: UTC second, 0-59.
        offset_hours: Whole-hour offset to add (may be negative).

    Returns:
        ``(year, month, day, hour, minute, second)`` in local time, with hour,
        day, month, and year carried/borrowed correctly across boundaries
        (including month lengths and leap years).
    """
    hour += offset_hours
    while hour >= 24:
        hour -= 24
        day += 1
        if day > _days_in_month(year, month):
            day = 1
            month += 1
            if month > 12:
                month = 1
                year += 1
    while hour < 0:
        hour += 24
        day -= 1
        if day < 1:
            month -= 1
            if month < 1:
                month = 12
                year -= 1
            day = _days_in_month(year, month)
    return (year, month, day, hour, minute, second)


def local_from_gps(date_str: str, utc_str: str, lon: float) -> tuple:
    """Build a local date/time tuple from GPS date, UTC time, and longitude.

    Args:
        date_str: GPS date as ``"YYYY-MM-DD"`` (e.g. from ``nmea.parse_rmc``).
        utc_str: GPS UTC time as ``"HH:MM:SSZ"`` (trailing ``Z`` tolerated).
        lon: Longitude in decimal degrees, used to derive the UTC offset.

    Returns:
        ``(year, month, day, weekday, hour, minute, second)`` in local time,
        where ``weekday`` is 0=Monday..6=Sunday — ready to splice into a
        ``machine.RTC().datetime()`` tuple as ``local[:3] + (wd,) + local[4:7] + (0,)``.
    """
    year = int(date_str[0:4])
    month = int(date_str[5:7])
    day = int(date_str[8:10])
    hour = int(utc_str[0:2])
    minute = int(utc_str[3:5])
    second = int(utc_str[6:8])
    offset = offset_hours_from_longitude(lon)
    ly, lmo, ld, lh, lmi, ls = utc_to_local(year, month, day, hour, minute, second, offset)
    return (ly, lmo, ld, weekday(ly, lmo, ld), lh, lmi, ls)
