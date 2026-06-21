"""MCU-micropython firmware for the gps project: ATGM336H NMEA collection over UART.

Reads every NMEA sentence that arrives in a 10-second window, parses satellite
and position data from the NMEA stream, and emits a structured JSON object.

"""

import os
import time
from collections import namedtuple

import ujson
from nmea import apply_parsed, build_utc_full, nmea_checksum_valid, parse_sentence

from atgm336h import GPS, DeviceNotFoundError
from boot_status_led import status

# Per-chip pin map — the authoritative wiring for this project, plain GPIO
# numbers. uart_id selects the UART peripheral the driver opens; tx drives the
# GPS RX line, rx carries the NMEA stream. Filled per chip by os.uname().machine
# dispatch at import.
Board = namedtuple("Board", ("name", "uart_id", "tx", "rx"))
_machine = os.uname().machine
if "ESP32S3" in _machine:
    BOARD = Board(name="ESP32-S3-Zero", uart_id=1, tx=17, rx=18)
elif "RP2350" in _machine:
    BOARD = Board(name="RP2350", uart_id=0, tx=0, rx=1)
else:
    BOARD = Board(name="RP2040-Zero", uart_id=0, tx=0, rx=1)

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
    """Parse NMEA sentences in WINDOW_MS windows, emit a result per window, repeat forever.

    Args:
        gps: An object with a ``readline() -> str | None`` method.

    Each successful window emits::

        {"window_ms": 10000, "utc": <str | null>, "sats_in_use": <n>,
         "sats_in_view": <n>, "hdop": <f>, "vdop": <f>, "pdop": <f>,
         "lat": <f>, "lon": <f>, "signals": [...]}

    An empty window (no GPS data) emits::

        {"diag": "no_data"}

    A UART exception emits a ``read_err`` diagnostic, resets the LED to
    streaming, and starts a fresh window immediately.  The most-recently seen
    GPS date is carried forward across windows and combined with the per-window
    UTC time to produce a full ISO-8601 timestamp.
    """
    status.streaming()
    cached_date: str | None = None
    while True:
        try:
            cached_date = _run_window(gps, cached_date)
        except Exception:  # noqa: BLE001
            status.read_err()
            emit({"diag": "read_err"})
            status.streaming()


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
            gps = GPS(bus_id=BOARD.uart_id, tx=BOARD.tx, rx=BOARD.rx)
        except DeviceNotFoundError:
            # No NMEA bytes on the UART — unwired/unpowered module or TX/RX swap.
            status.no_device()
            emit({"diag": "no_device"})
            time.sleep_ms(_INIT_ERR_PAUSE_MS)
            status.boot()
            continue
        except Exception:  # noqa: BLE001
            status.init_err()
            emit({"diag": "init_err"})
            time.sleep_ms(_INIT_ERR_PAUSE_MS)
            status.boot()
            continue
        stream(gps)


def _run_window(gps: object, cached_date: str | None) -> str | None:
    """Collect NMEA sentences for one WINDOW_MS window and emit a JSON result.

    Args:
        gps: An object with a ``readline() -> str | None`` method.
        cached_date: Most-recently seen GPS date (``"YYYY-MM-DD"``), or
            ``None`` if no date sentence has been received yet.

    Returns:
        Updated ``cached_date``; unchanged if no new date was seen this window.
        UART or I/O errors from ``gps.readline()`` propagate to the caller.
    """
    signals: dict = {}
    in_use_set: set = set()
    total_in_view: dict = {}
    dop: dict = {}
    position: dict = {}
    utc_time: str | None = None
    saw_data = False
    t_start = time.ticks_ms()
    while time.ticks_diff(time.ticks_ms(), t_start) < WINDOW_MS:
        line = gps.readline()
        if line is not None:
            if not nmea_checksum_valid(line):
                continue
            saw_data = True
            new_signals, new_in_use, new_total, new_dop, new_pos, new_parsed = parse_sentence(line)
            signals.update(new_signals)
            in_use_set |= new_in_use
            total_in_view.update(new_total)
            dop.update(new_dop)
            position.update(new_pos)
            utc_time, cached_date = apply_parsed(new_parsed, utc_time, cached_date)
        time.sleep_ms(_POLL_SLEEP_MS)
    if saw_data:
        emit(
            {
                "window_ms": WINDOW_MS,
                "utc": build_utc_full(utc_time, cached_date),
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
    return cached_date


main()
