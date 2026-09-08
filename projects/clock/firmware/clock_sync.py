"""GPS sentence parsing and RTC sync for the clock project."""

from nmea import apply_parsed, nmea_checksum_valid, parse_sentence
from tz_offset import offset_hours_from_longitude, utc_to_local_seconds, weekday


class ClockSynchronizer:
    """Keep GPS parse state and apply complete fixes to an RTC."""

    def __init__(self, rtc: object) -> None:
        """Bind synchronization state to one RTC."""
        self._rtc = rtc
        self.state = {"synced": False}
        self.synced = False
        self.boot_time = None

    def consume(self, line: str | None) -> None:
        """Parse one GPS line and update ``synced`` when a fix is complete.

        The first complete fix is latched into ``boot_time`` as the RTC parts
        tuple it just set, giving the uptime screen a fixed reference instant —
        the wall-clock moment this run became a real clock.
        """
        sync_from_line(line, self._rtc, self.state)
        self.synced = self.state.get("synced", False)
        if self.synced and self.boot_time is None:
            self.boot_time = tuple(self._rtc.datetime())[:7]


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
        0,
    )


def gps_offset(state: dict) -> int:
    """Return the startup timezone offset in seconds, deriving it from the first fix.

    Latched on the first fix so the displayed time never jumps mid-run: crossing a
    15-degree meridian would otherwise shift the clock by a whole hour.
    """
    if state.get("offset_s") is None:
        state["offset_s"] = offset_hours_from_longitude(state["lon"]) * 3600
    return state["offset_s"]


def sync_from_line(line: str | None, rtc: object, state: dict) -> None:
    """Parse one NMEA sentence and set the RTC when a complete fix is available."""
    if line is None or not nmea_checksum_valid(line):
        return
    _signals, _in_use, _total, _dop, position, parsed = parse_sentence(line)
    utc_time, cached_date = apply_parsed(parsed, state.get("utc"), state.get("date"))
    state["utc"] = utc_time
    state["date"] = cached_date
    lon = parsed.get("lon", position.get("lon"))
    if lon is not None:
        state["lon"] = lon
    if parsed.get("utc") is None or cached_date is None or state.get("lon") is None:
        return
    local = local_from_offset(cached_date, utc_time, gps_offset(state))
    rtc.datetime(local)
    state["synced"] = True
