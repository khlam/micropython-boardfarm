"""Pure-integer Gregorian calendar primitives shared across the tz_offset package.

These live in their own module so the POSIX TZ evaluator (``_posix``) can reuse
the leap-year, month-length, and weekday math without importing the package
``__init__`` — which would create an import cycle, since ``__init__`` imports
``_posix``. Everything here is integer-only with no I/O, so it runs identically on
the MCU and under host CPython pytest.
"""

_DAYS_IN_MONTH = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)

# Fixed ordinal anchor for the day-count <-> date conversion. GPS dates are always
# well after this, so the conversion never needs to represent earlier years.
_EPOCH_YEAR = 1970


def _is_leap(year: int) -> bool:
    """Return True when ``year`` is a Gregorian leap year."""
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def _days_in_month(year: int, month: int) -> int:
    """Return the number of days in ``month`` (1-12) of ``year``."""
    if month == 2 and _is_leap(year):
        return 29
    return _DAYS_IN_MONTH[month - 1]


def _sun0(year: int, month: int, day: int) -> int:
    """Return the day of week with 0=Sunday..6=Saturday via Sakamoto's algorithm.

    This is the Sunday-anchored intermediate the public ``weekday`` rotates into a
    Monday-anchored value. ``_posix`` uses it directly to resolve nth-weekday-of-
    month transition rules, which POSIX specifies in a Sunday-anchored basis.
    """
    t = (0, 3, 2, 5, 0, 3, 5, 1, 4, 6, 2, 4)
    y = year - (1 if month < 3 else 0)
    return (y + y // 4 - y // 100 + y // 400 + t[month - 1] + day) % 7


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
    # Sakamoto yields 0=Sunday..6=Saturday; rotate to 0=Monday..6=Sunday.
    return (_sun0(year, month, day) + 6) % 7


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


def _days_from_epoch(year: int, month: int, day: int) -> int:
    """Return the count of days from ``_EPOCH_YEAR``-01-01 to the given date.

    Assumes ``year >= _EPOCH_YEAR`` (always true for GPS dates). Walks years then
    months so it reuses ``_is_leap``/``_days_in_month`` rather than duplicating the
    Gregorian rules.
    """
    n = 0
    y = _EPOCH_YEAR
    while y < year:
        n += 366 if _is_leap(y) else 365
        y += 1
    mo = 1
    while mo < month:
        n += _days_in_month(year, mo)
        mo += 1
    return n + (day - 1)


def _date_from_days(n: int) -> tuple:
    """Inverse of ``_days_from_epoch``: map a day count back to ``(year, month, day)``."""
    y = _EPOCH_YEAR
    while True:
        year_days = 366 if _is_leap(y) else 365
        if n < year_days:
            break
        n -= year_days
        y += 1
    mo = 1
    while n >= _days_in_month(y, mo):
        n -= _days_in_month(y, mo)
        mo += 1
    return (y, mo, n + 1)


def utc_to_local_seconds(
    year: int,
    month: int,
    day: int,
    hour: int,
    minute: int,
    second: int,
    offset_seconds: int,
) -> tuple:
    """Apply a second-resolution offset to a UTC date/time, rolling over all fields.

    Unlike ``utc_to_local`` this accepts an arbitrary signed second offset, so it
    covers DST shifts and sub-hour zones (India +5:30, Nepal +5:45) that the
    whole-hour helper cannot. Done by converting to a day count plus seconds-of-day,
    adding the offset, and converting back with one ``divmod`` — no nested carry
    loops, and naturally correct across day/month/year/leap boundaries for offsets
    up to the ±14 h real-world range.

    Args:
        year: Four-digit UTC year.
        month: UTC month, 1-12.
        day: UTC day of month.
        hour: UTC hour, 0-23.
        minute: UTC minute, 0-59.
        second: UTC second, 0-59.
        offset_seconds: Signed offset to add, in seconds (may be negative).

    Returns:
        ``(year, month, day, hour, minute, second)`` in local time.
    """
    total = (
        _days_from_epoch(year, month, day) * 86400
        + hour * 3600
        + minute * 60
        + second
        + offset_seconds
    )
    days, sod = divmod(total, 86400)
    local_year, local_month, local_day = _date_from_days(days)
    return (local_year, local_month, local_day, sod // 3600, (sod % 3600) // 60, sod % 60)
