"""Pure NMEA-0183 sentence parsing helpers for the gps project.

All functions are stateless and free of I/O — safe to import on both the MCU
and the CPython host test environment.
"""


def nmea_checksum_valid(line: str) -> bool:
    """Verify the XOR checksum of an NMEA sentence.

    Args:
        line: A raw NMEA sentence string including the leading ``$`` and
            trailing ``*HH`` checksum suffix.

    Returns:
        ``True`` when the XOR of all bytes between ``$`` and ``*`` matches
        the two-hex-digit checksum field; ``False`` when the ``*`` delimiter
        is absent, the checksum field is not valid hex, or the values differ.
    """
    star = line.find("*")
    if star < 0 or star + 3 > len(line):
        return False
    try:
        expected = int(line[star + 1 : star + 3], 16)
    except ValueError:
        return False
    actual = 0
    for ch in line[1:star]:
        actual ^= ord(ch)
    return actual == expected


def parse_gsv(parts: list) -> tuple:
    """Extract per-satellite signal data from a GSV sentence.

    Args:
        parts: Comma-split NMEA fields (checksum already stripped from last field).

    Returns:
        ``(signals, total_in_view)`` where ``signals`` is a dict keyed by PRN
        (int) mapping to ``{"prn": int, "snr": int, "sys": str}`` and
        ``total_in_view`` maps the constellation code to total SV count.
        Satellites with no SNR are omitted.  Keying by PRN means repeated
        epochs within a window overwrite rather than append.
    """
    if len(parts) < 4:
        return {}, {}
    constellation = parts[0][1:3]
    total_in_view: dict = {}
    try:  # noqa: SIM105 — contextlib not available on MicroPython
        total_in_view[constellation] = int(parts[3])
    except ValueError:
        pass
    signals: dict = {}
    i = 4
    while i + 3 < len(parts):
        prn = parts[i]
        snr_raw = parts[i + 3].split("*")[0]
        if prn and snr_raw:
            try:
                prn_int = int(prn)
                signals[prn_int] = {"prn": prn_int, "snr": int(snr_raw), "sys": constellation}
            except ValueError:
                pass
        i += 4
    return signals, total_in_view


def parse_gsa(parts: list) -> tuple:
    """Extract satellites-in-use and DOP values from a GSA sentence.

    Args:
        parts: Comma-split NMEA fields (checksum stripped from last field).

    Returns:
        ``(in_use, dop)`` where ``in_use`` is a set of PRN strings and
        ``dop`` maps ``"pdop"``, ``"hdop"``, ``"vdop"`` to floats.  Multiple
        GSA sentences (one per constellation) are merged by the caller via
        set-union and dict-update.
    """
    in_use = {prn for prn in parts[3:15] if prn}
    dop: dict = {}
    if len(parts) > 17:
        try:
            dop["pdop"] = float(parts[15])
            dop["hdop"] = float(parts[16])
            dop["vdop"] = float(parts[17].split("*")[0])
        except (ValueError, IndexError):
            pass
    return in_use, dop


def parse_gga(parts: list) -> dict:
    """Extract decimal-degree lat/lon from a GGA sentence.

    Args:
        parts: Comma-split NMEA fields (checksum stripped from last field).

    Returns:
        ``{"lat": float, "lon": float}`` when a valid fix is present, or
        ``{}`` when fix quality is 0 or coordinates are absent.

    NMEA DDmm.mmmm format is converted to decimal degrees:
    ``DD + mm.mmmm / 60``.
    """
    if len(parts) < 7 or not parts[2] or parts[6] == "0":
        return {}
    try:
        lat_raw = float(parts[2])
        d = int(lat_raw / 100)
        lat = d + (lat_raw - d * 100) / 60.0
        if parts[3] == "S":
            lat = -lat
        lon_raw = float(parts[4])
        d = int(lon_raw / 100)
        lon = d + (lon_raw - d * 100) / 60.0
        if parts[5] == "W":
            lon = -lon
        return {"lat": round(lat, 6), "lon": round(lon, 6)}
    except (ValueError, IndexError):
        return {}


def parse_zda(parts: list) -> dict:
    """Extract UTC date and time from a ZDA sentence.

    Args:
        parts: Comma-split NMEA fields (checksum stripped from last field).

    Returns:
        ``{"date": str, "utc": str}`` where ``date`` is ``"YYYY-MM-DD"``
        and ``utc`` is ``"HH:MM:SSZ"``, or ``{}`` when the sentence is
        incomplete or contains invalid data.

    ZDA format: ``$GPZDA,hhmmss,dd,mm,yyyy<chk>``
    """
    if len(parts) < 6:
        return {}
    try:
        time_str = parts[1]
        day_str = parts[2]
        month_str = parts[3]
        year_str = parts[4]
        if not all([time_str, day_str, month_str, year_str]):
            return {}
        hh = int(time_str[0:2])
        mm = int(time_str[2:4])
        ss = int(time_str[4:6])
        dd = int(day_str)
        mm_val = int(month_str)
        yyyy = int(year_str)
        if not (0 <= hh <= 23 and 0 <= mm <= 59 and 0 <= ss <= 59):
            return {}
        if not (1 <= dd <= 31 and 1 <= mm_val <= 12):
            return {}
    except (ValueError, IndexError):
        return {}
    else:
        return {
            "date": f"{yyyy:04d}-{mm_val:02d}-{dd:02d}",
            "utc": f"{hh:02d}:{mm:02d}:{ss:02d}Z",
        }


def _parse_rmc_date(date_str: str) -> str | None:
    """Parse a 6-digit DDMMYY date field from RMC into YYYY-MM-DD, or None if invalid."""
    try:
        dd = int(date_str[0:2])
        mm_val = int(date_str[2:4])
        yy = int(date_str[4:6])
        if 1 <= dd <= 31 and 1 <= mm_val <= 12:
            return f"{2000 + yy:04d}-{mm_val:02d}-{dd:02d}"
    except (ValueError, IndexError):
        pass
    return None


def _parse_rmc_time_and_pos(parts: list) -> dict:
    """Extract UTC time, date, and position from RMC parts (status already validated as "A")."""
    time_str = parts[1]
    if not time_str:
        return {}
    hh = int(time_str[0:2])
    mm = int(time_str[2:4])
    ss = int(time_str[4:6])
    if not (0 <= hh <= 23 and 0 <= mm <= 59 and 0 <= ss <= 59):
        return {}
    utc_str = f"{hh:02d}:{mm:02d}:{ss:02d}Z"
    lat_raw = float(parts[3])
    lat_dir = parts[4]
    lon_raw = float(parts[5])
    lon_dir = parts[6]
    d = int(lat_raw / 100)
    lat = d + (lat_raw - d * 100) / 60.0
    if lat_dir == "S":
        lat = -lat
    d = int(lon_raw / 100)
    lon = d + (lon_raw - d * 100) / 60.0
    if lon_dir == "W":
        lon = -lon
    result: dict = {"utc": utc_str, "lat": round(lat, 6), "lon": round(lon, 6)}
    date_str = parts[9] if len(parts) > 9 else ""
    if date_str:
        date = _parse_rmc_date(date_str)
        if date is not None:
            result["date"] = date
    return result


def parse_rmc(parts: list) -> dict:
    """Extract UTC time and position from an RMC sentence.

    Args:
        parts: Comma-split NMEA fields (checksum stripped from last field).

    Returns:
        ``{"utc": str, "lat": float, "lon": float}`` (plus ``"date": str``
        when the date field is present and valid) when a fix is present
        (status ``"A"``), or ``{}`` when status is ``"V"`` (void) or
        coordinates are absent.

    RMC format: ``$GPRMC,hhmmss,A,llll.llll,a,lllll.llll,a,spd,crs,DDMMYY,...``
    """
    if len(parts) < 10:
        return {}
    if parts[2] != "A":
        return {}
    try:
        return _parse_rmc_time_and_pos(parts)
    except (ValueError, IndexError):
        return {}


def parse_sentence(line: str) -> tuple:
    """Dispatch one raw NMEA line and return parsed data for that sentence type.

    Args:
        line: A single raw NMEA string, checksum included.

    Returns:
        ``(signals, in_use, total_in_view, dop, position, parsed)`` where
        ``signals`` is a dict keyed by PRN int and ``parsed`` carries time/date
        fields (``"utc"``, ``"date"``) from ZDA/RMC sentences.  Each value is
        empty (``{}``, ``set()``) when the sentence type is unknown or carries
        no usable data.
    """
    parts = line.split("*", 1)[0].split(",")
    if not parts:
        return {}, set(), {}, {}, {}, {}
    tag = parts[0]
    signals, in_use, total_in_view, dop, position, parsed = {}, set(), {}, {}, {}, {}
    if tag.endswith("GSV"):
        signals, total_in_view = parse_gsv(parts)
    elif tag.endswith("GSA"):
        in_use, dop = parse_gsa(parts)
    elif tag in ("$GNGGA", "$GPGGA"):
        position = parse_gga(parts)
    elif tag.endswith("ZDA"):
        parsed = parse_zda(parts)
    elif tag.endswith("RMC"):
        parsed = parse_rmc(parts)
    return signals, in_use, total_in_view, dop, position, parsed


def apply_parsed(parsed: dict, utc_time: str | None, cached_date: str | None) -> tuple:
    """Merge UTC time and date fields from a parsed sentence into accumulated state.

    Args:
        parsed: Dict returned by a sentence parser; may contain ``"utc"``
            and/or ``"date"`` keys.
        utc_time: Most-recently seen UTC time string for this window, or ``None``.
        cached_date: Most-recently seen GPS date string across windows, or ``None``.

    Returns:
        ``(utc_time, cached_date)`` updated with any values present in ``parsed``.
    """
    if "utc" in parsed:
        utc_time = parsed["utc"]
    new_date = parsed.get("date")
    if new_date is not None and (cached_date is None or new_date > cached_date):
        cached_date = new_date
    return utc_time, cached_date


def build_utc_full(utc_time: str | None, cached_date: str | None) -> str | None:
    """Combine a cached GPS date and a window UTC time into an ISO-8601 timestamp.

    Args:
        utc_time: Time string in ``"HH:MM:SSZ"`` format, or ``None``.
        cached_date: Date string in ``"YYYY-MM-DD"`` format, or ``None``.

    Returns:
        ``"YYYY-MM-DDTHH:MM:SSZ"`` when both inputs are present, otherwise ``None``.
    """
    if utc_time is None or cached_date is None:
        return None
    return f"{cached_date}T{utc_time}"
