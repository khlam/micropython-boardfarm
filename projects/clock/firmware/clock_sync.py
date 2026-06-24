"""GPS sentence parsing and RTC sync for the clock project."""

import time

import ujson

from nmea import apply_parsed, nmea_checksum_valid, parse_sentence
from tz_offset import offset_seconds_from_gps, utc_to_local_seconds, weekday

_DAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")


def emit(obj: dict) -> None:
    """Print one line of compact JSON to the serial port.

    All firmware output must go through this helper; raw ``print()`` calls
    elsewhere pollute the serial stream and are silently dropped by the viz
    JSON parser.
    """
    print(ujson.dumps(obj))


def iso_local(local: tuple) -> str:
    """Format a local time tuple as an ISO-like timestamp for JSON output."""
    year, month, day, _weekday, hour, minute, second = local
    return f"{year:04d}-{month:02d}-{day:02d}T{hour:02d}:{minute:02d}:{second:02d}"


def rtc_datetime(local: tuple) -> tuple:
    """Convert local clock fields into an RTC datetime tuple."""
    return local[:4] + local[4:7] + (0,)


def parse_utc_parts(date_str: str, utc_str: str) -> tuple:
    """Split GPS date and UTC strings into integer date/time fields."""
    return (
        int(date_str[0:4]),
        int(date_str[5:7]),
        int(date_str[8:10]),
        int(utc_str[0:2]),
        int(utc_str[3:5]),
        int(utc_str[6:8]),
    )


def local_from_offset(date_str: str, utc_str: str, offset_s: int) -> tuple:
    """Convert a GPS UTC timestamp to an RTC-ready local tuple with a cached offset."""
    year, month, day, hour, minute, second = parse_utc_parts(date_str, utc_str)
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


def gps_offset(date_str: str, utc_str: str, state: dict) -> tuple:
    """Return the startup timezone offset, computing it from the first fix."""
    if state.get("offset_s") is None:
        offset_s, tz_abbrev = offset_seconds_from_gps(
            date_str,
            utc_str,
            state["lat"],
            state["lon"],
        )
        state["offset_s"] = offset_s
        state["tz_abbrev"] = tz_abbrev
    return state["offset_s"], state.get("tz_abbrev")


def sync_from_line(
    line: str | None,
    rtc: object,
    state: dict,
    emitter: object | None = None,
    clock: object | None = None,
) -> None:
    """Parse one NMEA sentence and set the RTC when a complete fix is available."""
    if line is None or not nmea_checksum_valid(line):
        return
    _signals, _in_use, _total, _dop, position, parsed = parse_sentence(line)
    utc_time, cached_date = apply_parsed(parsed, state.get("utc"), state.get("date"))
    state["utc"] = utc_time
    state["date"] = cached_date
    lat = parsed.get("lat", position.get("lat"))
    if lat is not None:
        state["lat"] = lat
    lon = parsed.get("lon", position.get("lon"))
    if lon is not None:
        state["lon"] = lon
    if (
        parsed.get("utc") is None
        or cached_date is None
        or state.get("lat") is None
        or state.get("lon") is None
    ):
        return
    if emitter is None:
        emitter = emit
    if clock is None:
        clock = time
    now = clock.ticks_ms()
    offset_s, tz_abbrev = gps_offset(cached_date, utc_time, state)
    local = local_from_offset(cached_date, utc_time, offset_s)
    rtc.datetime(rtc_datetime(local))
    state["synced"] = True
    emitter(
        {
            "fix": True,
            "lat": state["lat"],
            "lon": state["lon"],
            "offset_h": offset_s // 3600,
            "offset_min": offset_s // 60,
            "tz": tz_abbrev,
            "local": iso_local(local),
            "day": _DAYS[local[3]],
            "t": now,
        }
    )
