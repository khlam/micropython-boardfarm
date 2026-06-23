"""MCU MicroPython firmware for the clock project.

Reads UTC date/time and longitude from an ATGM336H GPS over UART, derives a
fixed local offset from longitude, sets the onboard RTC, and shows the current
local time and date on the 16x32 MAX7219 matrix.
"""

import os
import time
from collections import namedtuple

import ujson
from machine import RTC

from atgm336h import GPS
from boot_status_led import status
from max7219 import MAX7219
from nmea import apply_parsed, nmea_checksum_valid, parse_sentence
from pixel_display import Frame
from tz_offset import local_from_gps, offset_hours_from_longitude

UartWiring = namedtuple("UartWiring", ("bus_id", "tx", "rx"))
DisplayWiring = namedtuple(
    "DisplayWiring",
    (
        "spi_id",
        "sck",
        "mosi",
        "cs",
        "width_pixels",
        "height_pixels",
        "intensity_min",
        "intensity_max",
        "intensity_limit",
    ),
)
Board = namedtuple("Board", ("name", "uart", "display"))

_DISPLAY_WIDTH_PIXELS = 32
_DISPLAY_HEIGHT_PIXELS = 16
_DISPLAY_INTENSITY_MIN = 0
_DISPLAY_INTENSITY_MAX = 15
_DISPLAY_INTENSITY_LIMIT = 0.2

_machine = os.uname().machine
if "ESP32S3" in _machine:
    BOARD = Board(
        name="ESP32-S3-Zero",
        uart=UartWiring(bus_id=1, tx=13, rx=12),
        display=DisplayWiring(
            spi_id=1,
            sck=5,
            mosi=6,
            cs=7,
            width_pixels=_DISPLAY_WIDTH_PIXELS,
            height_pixels=_DISPLAY_HEIGHT_PIXELS,
            intensity_min=_DISPLAY_INTENSITY_MIN,
            intensity_max=_DISPLAY_INTENSITY_MAX,
            intensity_limit=_DISPLAY_INTENSITY_LIMIT,
        ),
    )
elif "RP2350" in _machine:
    BOARD = Board(
        name="RP2350",
        uart=UartWiring(bus_id=1, tx=4, rx=5),
        display=DisplayWiring(
            spi_id=1,
            sck=10,
            mosi=11,
            cs=9,
            width_pixels=_DISPLAY_WIDTH_PIXELS,
            height_pixels=_DISPLAY_HEIGHT_PIXELS,
            intensity_min=_DISPLAY_INTENSITY_MIN,
            intensity_max=_DISPLAY_INTENSITY_MAX,
            intensity_limit=_DISPLAY_INTENSITY_LIMIT,
        ),
    )
else:
    BOARD = Board(
        name="RP2040-Zero",
        uart=UartWiring(bus_id=0, tx=0, rx=1),
        display=DisplayWiring(
            spi_id=1,
            sck=26,
            mosi=27,
            cs=28,
            width_pixels=_DISPLAY_WIDTH_PIXELS,
            height_pixels=_DISPLAY_HEIGHT_PIXELS,
            intensity_min=_DISPLAY_INTENSITY_MIN,
            intensity_max=_DISPLAY_INTENSITY_MAX,
            intensity_limit=_DISPLAY_INTENSITY_LIMIT,
        ),
    )

_BOOT_PAUSE_MS = 300
_INIT_ERR_PAUSE_MS = 1_000
_POLL_SLEEP_MS = 50
_REASSERT_MS = 5_000
_WAIT_TOP = "GPS"
_WAIT_BOT = "WAIT"
_DAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")


def emit(obj: dict) -> None:
    """Print one line of compact JSON to the serial port.

    All firmware output must go through this helper; raw ``print()`` calls
    elsewhere pollute the serial stream and are silently dropped by the viz
    JSON parser.
    """
    print(ujson.dumps(obj))


def _iso_local(local: tuple) -> str:
    """Format a local time tuple as an ISO-like timestamp for JSON output."""
    year, month, day, _weekday, hour, minute, second = local
    return f"{year:04d}-{month:02d}-{day:02d}T{hour:02d}:{minute:02d}:{second:02d}"


def _rtc_datetime(local: tuple) -> tuple:
    """Convert ``tz_offset.local_from_gps`` output into an RTC datetime tuple."""
    return local[:4] + local[4:7] + (0,)


def _display_lines(rtc: object, *, synced: bool) -> tuple:
    """Return the two matrix lines for the current clock state."""
    if not synced:
        return _WAIT_TOP, _WAIT_BOT
    _year, month, day, _weekday, hour, minute, second, _subsecond = rtc.datetime()
    separator = ":" if second % 2 == 0 else " "
    return f"{hour:02d}{separator}{minute:02d}", f"{month}/{day}"


def _show(display: object, state: dict, top: str, bottom: str) -> None:
    """Refresh the display only when text changes; otherwise periodically heal it."""
    lines = (top, bottom)
    now = time.ticks_ms()
    if state.get("shown") != lines:
        display.show(Frame.text_lines(lines))
        state["shown"] = lines
        state["last_reassert_ms"] = now
        return
    last_reassert = state.get("last_reassert_ms")
    if last_reassert is None or time.ticks_diff(now, last_reassert) >= _REASSERT_MS:
        display.show(Frame.text_lines(lines))
        state["last_reassert_ms"] = now


def _refresh_display(display: object, rtc: object, state: dict) -> None:
    """Render waiting text or the current RTC-backed local time/date."""
    top, bottom = _display_lines(rtc, synced=bool(state.get("synced")))
    _show(display, state, top, bottom)


def _sync_from_line(line: str | None, rtc: object, state: dict) -> None:
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
    local = local_from_gps(cached_date, utc_time, state["lon"])
    rtc.datetime(_rtc_datetime(local))
    state["synced"] = True
    emit(
        {
            "fix": True,
            "lon": state["lon"],
            "offset_h": offset_hours_from_longitude(state["lon"]),
            "local": _iso_local(local),
            "day": _DAYS[local[3]],
            "t": time.ticks_ms(),
        }
    )


def run(gps: object, display: object, rtc: object) -> None:
    """Read GPS sentences, keep the RTC current, and drive the display.

    Args:
        gps: Object with ``readline() -> str | None``.
        display: Object exposing ``show(frame)``.
        rtc: ``machine.RTC`` instance used as the clock source between fixes.
    """
    status.streaming()
    state = {"synced": False}
    while True:
        try:
            _sync_from_line(gps.readline(), rtc, state)
            _refresh_display(display, rtc, state)
            time.sleep_ms(_POLL_SLEEP_MS)
        except Exception:  # noqa: BLE001
            status.read_err()
            emit({"diag": "read_err"})
            time.sleep_ms(_POLL_SLEEP_MS)
            status.streaming()


def main() -> None:
    """Run boot -> GPS/display init -> live clock loop. MicroPython entry point.

    LED sequence: white -> cyan (opening buses) -> green (running).
    On init failure: cyan -> magenta -> white (retry).
    """
    status.boot()
    time.sleep_ms(_BOOT_PAUSE_MS)
    while True:
        status.i2c_init()
        try:
            display = MAX7219(
                spi_id=BOARD.display.spi_id,
                sck=BOARD.display.sck,
                mosi=BOARD.display.mosi,
                cs=BOARD.display.cs,
                width_pixels=BOARD.display.width_pixels,
                height_pixels=BOARD.display.height_pixels,
                intensity_min=BOARD.display.intensity_min,
                intensity_max=BOARD.display.intensity_max,
                intensity_limit=BOARD.display.intensity_limit,
            )
            gps = GPS(bus_id=BOARD.uart.bus_id, tx=BOARD.uart.tx, rx=BOARD.uart.rx)
            rtc = RTC()
        except Exception:  # noqa: BLE001
            status.init_err()
            emit({"diag": "init_err"})
            time.sleep_ms(_INIT_ERR_PAUSE_MS)
            status.boot()
            continue
        run(gps, display, rtc)


main()
