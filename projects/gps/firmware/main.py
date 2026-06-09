"""MCU-micropython firmware for the gps project: ATGM336H NMEA collection over UART.

Reads every NMEA sentence that arrives in a 10-second window, parses satellite
and position data from the NMEA stream, and emits a structured JSON object.

"""

import time

import ujson

from atgm336h import connect
from boot_status_led import status

WINDOW_MS = 10_000
_POLL_SLEEP_MS = 10
_BOOT_PAUSE_MS = 300
_INIT_ERR_PAUSE_MS = 1_000


def emit(obj: dict) -> None:
    """Print one line of compact JSON to the serial port.

    All firmware output must go through this helper; raw ``print()`` calls
    elsewhere pollute the serial stream and are silently dropped by the viz
    JSON parser.
    """
    print(ujson.dumps(obj))


def stream(gps: object) -> None:
    """Parse NMEA sentences for WINDOW_MS as they arrive, emit a result, repeat forever.

    Args:
        gps: An object with a ``readline() -> str | None`` method.

    Each successful window emits::

        {"window_ms": 10000, "utc": <str | null>, "sats_in_use": <n>,
         "sats_in_view": <n>, "hdop": <f>, "vdop": <f>, "pdop": <f>,
         "lat": <f>, "lon": <f>, "signals": [...]}

    An empty window (no GPS data) emits::

        {"diag": "no_data"}

    A UART exception emits a ``read_err`` diagnostic, resets the LED to
    streaming, and starts a fresh window immediately.
    """
    status.streaming()
    while True:
        signals: dict = {}
        in_use_set: set = set()
        total_in_view: dict = {}
        dop: dict = {}
        position: dict = {}
        utc: dict = {}
        saw_data = False
        t_start = time.ticks_ms()
        try:
            while time.ticks_diff(time.ticks_ms(), t_start) < WINDOW_MS:
                line = gps.readline()
                if line is not None:
                    saw_data = True
                    new_signals, new_in_use, new_total, new_dop, new_pos, new_utc = _parse_sentence(
                        line
                    )
                    signals.update(new_signals)
                    in_use_set |= new_in_use
                    total_in_view.update(new_total)
                    dop.update(new_dop)
                    position.update(new_pos)
                    utc.update(new_utc)
                time.sleep_ms(_POLL_SLEEP_MS)
        except Exception:  # noqa: BLE001
            status.read_err()
            emit({"diag": "read_err"})
            status.streaming()
            continue
        if saw_data:
            emit(
                {
                    "window_ms": WINDOW_MS,
                    "utc": utc.get("utc"),
                    "sats_in_use": len(in_use_set),
                    "sats_in_view": sum(total_in_view.values()),
                    "hdop": dop.get("hdop"),
                    "vdop": dop.get("vdop"),
                    "pdop": dop.get("pdop"),
                    "lat": position.get("lat"),
                    "lon": position.get("lon"),
                    "signals": list(signals.values()),
                }
            )
        else:
            emit({"diag": "no_data"})


def main() -> None:
    """Run boot → UART init → stream. MicroPython entry point.

    LED sequence: white → cyan (UART opening) → green (streaming).
    On UART failure: cyan → magenta → white (retry).
    """
    status.boot()
    time.sleep_ms(_BOOT_PAUSE_MS)
    while True:
        status.i2c_init()
        try:
            gps = connect()
        except Exception:  # noqa: BLE001
            status.init_err()
            emit({"diag": "init_err"})
            time.sleep_ms(_INIT_ERR_PAUSE_MS)
            status.boot()
            continue
        stream(gps)


def _parse_gsv(parts: list) -> tuple:
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


def _parse_gsa(parts: list) -> tuple:
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


def _parse_gga(parts: list) -> dict:
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


def _parse_zda(parts: list) -> dict:
    """Extract UTC date and time from a ZDA sentence.

    Args:
        parts: Comma-split NMEA fields (checksum stripped from last field).

    Returns:
        ``{"utc": str}`` with format ``"YYYY-MM-DDTHH:MM:SSZ"`` when all
        fields are valid, or ``{}`` when the sentence is incomplete or
        contains invalid data.

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
        utc_str = f"{yyyy:04d}-{mm_val:02d}-{dd:02d}T{hh:02d}:{mm:02d}:{ss:02d}Z"
    except (ValueError, IndexError):
        return {}
    return {"utc": utc_str}


def _parse_rmc_time_and_pos(parts: list) -> dict:
    """Extract UTC time and position from RMC parts (status already validated as "A")."""
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
    return {"utc": utc_str, "lat": round(lat, 6), "lon": round(lon, 6)}


def _parse_rmc(parts: list) -> dict:
    """Extract UTC time and position from an RMC sentence.

    Args:
        parts: Comma-split NMEA fields (checksum stripped from last field).

    Returns:
        ``{"utc": str, "lat": float, "lon": float}`` when a valid fix is
        present (status ``"A"``), or ``{}`` when status is ``"V"`` (void)
        or coordinates are absent.

    RMC format: ``$GPRMC,hhmmss,A,llll,llll,xx.x,x.x,xxxx,x.x,a,ddmmyyyy,x.x,a*hh<chk>``
    """
    if len(parts) < 10:
        return {}
    if parts[2] != "A":
        return {}
    try:
        return _parse_rmc_time_and_pos(parts)
    except (ValueError, IndexError):
        return {}


def _parse_sentence(line: str) -> tuple:
    """Dispatch one raw NMEA line and return parsed data for that sentence type.

    Args:
        line: A single raw NMEA string, checksum included.

    Returns:
        ``(signals, in_use, total_in_view, dop, position, utc)`` where
        ``signals`` is a dict keyed by PRN int.  Each value is empty
        (``{}``, ``set()``) when the sentence type is unknown or carries no
        usable data.
    """
    parts = line.split("*", 1)[0].split(",")
    if not parts:
        return {}, set(), {}, {}, {}, {}
    tag = parts[0]
    signals, in_use, total_in_view, dop, position, utc = {}, set(), {}, {}, {}, {}
    if tag.endswith("GSV"):
        signals, total_in_view = _parse_gsv(parts)
    elif tag.endswith("GSA"):
        in_use, dop = _parse_gsa(parts)
    elif tag in ("$GNGGA", "$GPGGA"):
        position = _parse_gga(parts)
    elif tag.endswith("ZDA"):
        utc = _parse_zda(parts)
    elif tag.endswith("RMC"):
        utc = _parse_rmc(parts)
    return signals, in_use, total_in_view, dop, position, utc


main()
