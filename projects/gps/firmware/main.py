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

        {"window_ms": 10000, "sats_in_use": <n>, "sats_in_view": <n>,
         "hdop": <f>, "vdop": <f>, "pdop": <f>, "lat": <f>, "lon": <f>, "signals": [...]}

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
        saw_data = False
        t_start = time.ticks_ms()
        try:
            while time.ticks_diff(time.ticks_ms(), t_start) < WINDOW_MS:
                line = gps.readline()
                if line is not None:
                    saw_data = True
                    new_signals, new_in_use, new_total, new_dop, new_pos = _parse_sentence(line)
                    signals.update(new_signals)
                    in_use_set |= new_in_use
                    total_in_view.update(new_total)
                    dop.update(new_dop)
                    position.update(new_pos)
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


def _parse_sentence(line: str) -> tuple:
    """Dispatch one raw NMEA line and return parsed data for that sentence type.

    Args:
        line: A single raw NMEA string, checksum included.

    Returns:
        ``(signals, in_use, total_in_view, dop, position)`` where ``signals``
        is a dict keyed by PRN int.  Each value is empty (``{}``, ``set()``)
        when the sentence type is unknown or carries no usable data.
    """
    parts = line.split("*", 1)[0].split(",")
    if not parts:
        return {}, set(), {}, {}, {}
    tag = parts[0]
    if tag.endswith("GSV"):
        signals, total_in_view = _parse_gsv(parts)
        return signals, set(), total_in_view, {}, {}
    if tag.endswith("GSA"):
        in_use, dop = _parse_gsa(parts)
        return {}, in_use, {}, dop, {}
    if tag in ("$GNGGA", "$GPGGA"):
        return {}, set(), {}, {}, _parse_gga(parts)
    return {}, set(), {}, {}, {}


main()
