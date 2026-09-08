"""GPS sentence parsing and RTC sync for the clock project."""

from nmea import apply_parsed, nmea_checksum_valid, parse_sentence
from tz_offset import offset_hours_from_longitude, utc_to_local_seconds, weekday


class ClockSynchronizer:
    """Accumulate NMEA fields until a fix is complete, then apply it to an RTC."""

    def __init__(self, rtc: object) -> None:
        """Bind synchronization state to one RTC."""
        self._rtc = rtc
        self._date = None
        self._lon = None
        self._offset_s = None
        self.synced = False
        self.boot_time = None

    def consume(self, line: str | None) -> None:
        """Parse one GPS line and set the RTC once time, date, and position are known.

        Date and longitude are cached across sentences; UTC must be fresh in
        the current sentence. The first complete fix latches ``boot_time``
        as the RTC parts tuple it just set, giving the uptime screen a fixed
        reference instant — the wall-clock moment this run became a real clock.
        """
        if line is None or not nmea_checksum_valid(line):
            return
        _signals, _in_use, _total, _dop, position, parsed = parse_sentence(line)
        utc, self._date = apply_parsed(parsed, None, self._date)
        lon = parsed.get("lon", position.get("lon"))
        if lon is not None:
            self._lon = lon
        if utc is None or self._date is None or self._lon is None:
            return
        if self._offset_s is None:
            # Latched on the first fix so the displayed time never jumps mid-run:
            # crossing a 15-degree meridian would otherwise shift it a whole hour.
            self._offset_s = offset_hours_from_longitude(self._lon) * 3600
        self._rtc.datetime(_local_datetime(self._date, utc, self._offset_s))
        self.synced = True
        if self.boot_time is None:
            self.boot_time = tuple(self._rtc.datetime())[:7]


def _local_datetime(date_str: str, utc_str: str, offset_s: int) -> tuple:
    """Convert a GPS UTC timestamp to an RTC-ready local tuple at a fixed offset."""
    year, month, day, hour, minute, second = utc_to_local_seconds(
        int(date_str[0:4]),
        int(date_str[5:7]),
        int(date_str[8:10]),
        int(utc_str[0:2]),
        int(utc_str[3:5]),
        int(utc_str[6:8]),
        offset_s,
    )
    return (
        year,
        month,
        day,
        weekday(year, month, day),
        hour,
        minute,
        second,
        0,
    )
