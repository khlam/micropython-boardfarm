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


def _parse_gsv(parts: list, signals: list, total_in_view: dict) -> None:
    """Extract per-satellite signal data from a GSV sentence.

    Args:
        parts: Comma-split NMEA fields (checksum already stripped from last field).
        signals: List to append ``{"prn": int, "snr": int, "sys": str}`` dicts into.
        total_in_view: Dict keyed by constellation code updated with total SV count.

    The constellation code is derived from the talker ID: ``$GPGSV`` → ``"GP"``,
    ``$BDGSV`` → ``"BD"``.  Satellites with an empty SNR field are skipped (no
    signal lock on that SV).
    """
    if len(parts) < 4:
        return
    constellation = parts[0][1:3]
    try:  # noqa: SIM105 — contextlib not available on MicroPython
        total_in_view[constellation] = int(parts[3])
    except ValueError:
        pass
    i = 4
    while i + 3 < len(parts):
        prn = parts[i]
        snr_raw = parts[i + 3].split("*")[0]
        if prn and snr_raw:
            try:  # noqa: SIM105 — contextlib not available on MicroPython
                signals.append({"prn": int(prn), "snr": int(snr_raw), "sys": constellation})
            except ValueError:
                pass
        i += 4


def _parse_gsa(parts: list, in_use_set: set, dop: dict) -> None:
    """Extract satellites-in-use and DOP values from a GSA sentence.

    Args:
        parts: Comma-split NMEA fields (checksum stripped from last field).
        in_use_set: Set of PRN strings to add active satellite IDs into.
        dop: Dict updated with ``"pdop"``, ``"hdop"``, and ``"vdop"`` floats.

    Multiple GSA sentences (one per constellation) are merged: PRNs accumulate
    into ``in_use_set`` and DOP values are overwritten (they are identical across
    the constellation pair in practice).
    """
    for prn in parts[3:15]:
        if prn:
            in_use_set.add(prn)
    if len(parts) > 17:
        try:
            dop["pdop"] = float(parts[15])
            dop["hdop"] = float(parts[16])
            dop["vdop"] = float(parts[17].split("*")[0])
        except (ValueError, IndexError):
            pass


def _parse_gga(parts: list, position: dict) -> None:
    """Extract decimal-degree lat/lon from a GGA sentence.

    Args:
        parts: Comma-split NMEA fields (checksum stripped from last field).
        position: Dict updated with ``"lat"`` and ``"lon"`` floats when a valid
            fix is present.  Skipped when fix quality is 0 or coordinates are
            absent.

    NMEA DDmm.mmmm format is converted to decimal degrees:
    ``DD + mm.mmmm / 60``.
    """
    if len(parts) < 7 or not parts[2] or parts[6] == "0":
        return
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
        position["lat"] = round(lat, 6)
        position["lon"] = round(lon, 6)
    except (ValueError, IndexError):
        pass


def _parse_window(sentences: list) -> dict:
    """Parse a window of raw NMEA sentences into structured GPS metrics.

    Args:
        sentences: Raw NMEA strings collected during one window.

    Returns:
        Dict with keys ``sats_in_use``, ``sats_in_view``, ``hdop``, ``vdop``,
        ``pdop``, ``lat``, ``lon``, and ``signals`` (list of per-satellite
        ``{"prn", "snr", "sys"}`` dicts).  DOP and position values are ``None``
        when no relevant sentences were seen.
    """
    in_use_set: set = set()
    total_in_view: dict = {}
    dop: dict = {}
    position: dict = {}
    signals: list = []

    for sentence in sentences:
        parts = sentence.split("*")[0].split(",")
        if not parts:
            continue
        tag = parts[0]
        if tag.endswith("GSV"):
            _parse_gsv(parts, signals, total_in_view)
        elif tag.endswith("GSA"):
            _parse_gsa(parts, in_use_set, dop)
        elif tag in ("$GNGGA", "$GPGGA"):
            _parse_gga(parts, position)

    return {
        "sats_in_use": len(in_use_set),
        "sats_in_view": sum(total_in_view.values()),
        "hdop": dop.get("hdop"),
        "vdop": dop.get("vdop"),
        "pdop": dop.get("pdop"),
        "lat": position.get("lat"),
        "lon": position.get("lon"),
        "signals": signals,
    }


def emit(obj: dict) -> None:
    """Print one line of compact JSON to the serial port.

    All firmware output must go through this helper; raw ``print()`` calls
    elsewhere pollute the serial stream and are silently dropped by the viz
    JSON parser.
    """
    print(ujson.dumps(obj))


def stream(gps: object) -> None:
    """Collect NMEA sentences for WINDOW_MS, emit a batch, repeat forever.

    Args:
        gps: An object with a ``readline() -> str | None`` method.

    Each successful window emits::

        {"t": <ms>, "window_ms": 10000, "sats_in_use": <n>, "sats_in_view": <n>,
         "hdop": <f>, "vdop": <f>, "pdop": <f>, "lat": <f>, "lon": <f>, "signals": [...]}

    An empty window (no GPS data) emits::

        {"diag": "no_data", "t": <ms>}

    A UART exception emits a ``read_err`` diagnostic, resets the LED to
    streaming, and starts a fresh window immediately.
    """
    status.streaming()
    while True:
        sentences: list[str] = []
        t_start = time.ticks_ms()
        try:
            while time.ticks_diff(time.ticks_ms(), t_start) < WINDOW_MS:
                line = gps.readline()
                if line is not None:
                    sentences.append(line)
                time.sleep_ms(_POLL_SLEEP_MS)
        except Exception:  # noqa: BLE001
            status.read_err()
            emit({"diag": "read_err"})
            status.streaming()
            continue
        if sentences:
            payload = {"t": time.ticks_ms(), "window_ms": WINDOW_MS}
            payload.update(_parse_window(sentences))
            emit(payload)
        else:
            emit({"diag": "no_data", "t": time.ticks_ms()})


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


main()
