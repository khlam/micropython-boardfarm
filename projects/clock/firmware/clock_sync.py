"""GPS sentence parsing and RTC sync for the clock project."""

from nmea import apply_parsed, nmea_checksum_valid, parse_sentence
from tz_offset import offset_seconds_from_gps, utc_to_local_seconds, weekday


class ClockSynchronizer:
    """Keep GPS parse state and apply complete fixes to an RTC."""

    def __init__(self, rtc: object) -> None:
        """Bind synchronization state to one RTC."""
        self._rtc = rtc
        self.state = {"synced": False}
        self.synced = False

    def consume(self, line: str | None) -> None:
        """Parse one GPS line and update ``synced`` when a fix is complete."""
        sync_from_line(line, self._rtc, self.state)
        self.synced = self.state.get("synced", False)


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


def sync_from_line(line: str | None, rtc: object, state: dict) -> None:
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
    offset_s, _tz_abbrev = gps_offset(cached_date, utc_time, state)
    local = local_from_offset(cached_date, utc_time, offset_s)
    rtc.datetime(rtc_datetime(local))
    state["synced"] = True
