"""Convert GPS UTC date/time to local time using a longitude-derived UTC offset.

MicroPython has no timezone database, so the offset is the nautical-style
approximation ``round(lon / 15)`` clamped to the real UTC range. It ignores
political timezone boundaries and daylight saving; see the README caveats.

Everything here is pure integer math with no I/O, so the same code runs on the MCU
and under host CPython pytest. There is nothing chip-specific, so this package has
no per-chip backends.
"""

from tz_offset._calendar import days_from_epoch, utc_to_local_seconds, weekday

__all__ = ["days_from_epoch", "offset_hours_from_longitude", "utc_to_local_seconds", "weekday"]

# round(lon/15) can reach ±13 near the date line; clamp to the real UTC range.
_MIN_OFFSET = -12
_MAX_OFFSET = 14


def offset_hours_from_longitude(lon: float) -> int:
    """Derive a whole-hour UTC offset from longitude.

    Args:
        lon: Longitude in decimal degrees (east positive, west negative).

    Returns:
        ``round(lon / 15)`` clamped to ``[-12, 14]``.
    """
    offset = round(lon / 15)
    if offset < _MIN_OFFSET:
        return _MIN_OFFSET
    if offset > _MAX_OFFSET:
        return _MAX_OFFSET
    return offset
