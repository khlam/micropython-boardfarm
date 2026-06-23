"""MCU MicroPython firmware for the clock project.

Reads UTC date/time and longitude from an ATGM336H GPS over UART, derives a
fixed local offset from longitude, sets the onboard RTC, and shows the selected
local clock face on the 16x32 MAX7219 matrix.
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
from tz_offset import local_from_gps, offset_seconds_from_gps

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
        "intensity_limit",
    ),
)
Board = namedtuple("Board", ("name", "uart", "display"))

_DISPLAY_WIDTH_PIXELS = 32
_DISPLAY_HEIGHT_PIXELS = 16
_DISPLAY_INTENSITY_LIMIT = 0.01

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
            intensity_limit=_DISPLAY_INTENSITY_LIMIT,
        ),
    )

_BOOT_PAUSE_MS = 300
_INIT_ERR_PAUSE_MS = 1_000
_POLL_SLEEP_MS = 50
_REASSERT_MS = 5_000
_WAIT_TOP = "GPS"
_WAIT_BOT = "WAIT"
_CLOCK_ROW_HEIGHT = 8
_CLOCK_BOTTOM_Y_OFFSET = 1
_COMPACT_GLYPH_HEIGHT = 7
_COMPACT_GAP_PIXELS = 1
_COMPACT_ON = 255
_COMPACT_GLYPHS = {
    " ": (
        "0",
        "0",
        "0",
        "0",
        "0",
        "0",
        "0",
    ),
    ":": (
        "0",
        "0",
        "1",
        "0",
        "1",
        "0",
        "0",
    ),
    "0": (
        "111",
        "101",
        "101",
        "101",
        "101",
        "101",
        "111",
    ),
    "1": (
        "010",
        "110",
        "010",
        "010",
        "010",
        "010",
        "111",
    ),
    "2": (
        "111",
        "001",
        "001",
        "111",
        "100",
        "100",
        "111",
    ),
    "3": (
        "111",
        "001",
        "001",
        "111",
        "001",
        "001",
        "111",
    ),
    "4": (
        "101",
        "101",
        "101",
        "111",
        "001",
        "001",
        "001",
    ),
    "5": (
        "111",
        "100",
        "100",
        "111",
        "001",
        "001",
        "111",
    ),
    "6": (
        "111",
        "100",
        "100",
        "111",
        "101",
        "101",
        "111",
    ),
    "7": (
        "111",
        "001",
        "001",
        "010",
        "010",
        "010",
        "010",
    ),
    "8": (
        "111",
        "101",
        "101",
        "111",
        "101",
        "101",
        "111",
    ),
    "9": (
        "111",
        "101",
        "101",
        "111",
        "001",
        "001",
        "111",
    ),
    "A": (
        "010",
        "101",
        "101",
        "111",
        "101",
        "101",
        "101",
    ),
    "B": (
        "110",
        "101",
        "101",
        "110",
        "101",
        "101",
        "110",
    ),
    "C": (
        "111",
        "100",
        "100",
        "100",
        "100",
        "100",
        "111",
    ),
    "D": (
        "110",
        "101",
        "101",
        "101",
        "101",
        "101",
        "110",
    ),
    "E": (
        "111",
        "100",
        "100",
        "110",
        "100",
        "100",
        "111",
    ),
    "F": (
        "111",
        "100",
        "100",
        "110",
        "100",
        "100",
        "100",
    ),
    "G": (
        "111",
        "100",
        "100",
        "101",
        "101",
        "101",
        "111",
    ),
    "H": (
        "101",
        "101",
        "101",
        "111",
        "101",
        "101",
        "101",
    ),
    "I": (
        "111",
        "010",
        "010",
        "010",
        "010",
        "010",
        "111",
    ),
    "J": (
        "001",
        "001",
        "001",
        "001",
        "101",
        "101",
        "111",
    ),
    "L": (
        "100",
        "100",
        "100",
        "100",
        "100",
        "100",
        "111",
    ),
    "M": (
        "10001",
        "11011",
        "10101",
        "10001",
        "10001",
        "10001",
        "10001",
    ),
    "N": (
        "1001",
        "1101",
        "1011",
        "1001",
        "1001",
        "1001",
        "1001",
    ),
    "O": (
        "111",
        "101",
        "101",
        "101",
        "101",
        "101",
        "111",
    ),
    "P": (
        "110",
        "101",
        "101",
        "110",
        "100",
        "100",
        "100",
    ),
    "R": (
        "110",
        "101",
        "101",
        "110",
        "101",
        "101",
        "101",
    ),
    "S": (
        "111",
        "100",
        "100",
        "111",
        "001",
        "001",
        "111",
    ),
    "T": (
        "111",
        "010",
        "010",
        "010",
        "010",
        "010",
        "010",
    ),
    "U": (
        "101",
        "101",
        "101",
        "101",
        "101",
        "101",
        "111",
    ),
    "V": (
        "101",
        "101",
        "101",
        "101",
        "101",
        "101",
        "010",
    ),
    "Y": (
        "101",
        "101",
        "101",
        "010",
        "010",
        "010",
        "010",
    ),
}
_MONTHS = (
    "Jan",
    "Feb",
    "March",
    "April",
    "May",
    "June",
    "July",
    "Aug",
    "Sept",
    "Oct",
    "Nov",
    "Dec",
)
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


def _format_time(hour: int, minute: int) -> str:
    """Format a 24-hour clock value as compact 12-hour time plus meridiem."""
    display_hour = hour % 12
    if display_hour == 0:
        display_hour = 12
    meridiem = "AM" if hour < 12 else "PM"
    return f"{display_hour:02d}:{minute:02d} {meridiem}"


def _format_date(month: int, day: int) -> str:
    """Format the date with a month name instead of a numeric month."""
    return f"{_MONTHS[month - 1]} {day}"


def _display_lines(rtc: object, *, synced: bool) -> tuple:
    """Return matrix text and colon visibility for the current clock state."""
    if not synced:
        return _WAIT_TOP, _WAIT_BOT, True
    _year, month, day, _weekday, hour, minute, second, _subsecond = rtc.datetime()
    return _format_time(hour, minute), _format_date(month, day), second % 2 == 0


def _compact_glyph(char: str) -> tuple:
    """Return a compact display glyph, using a blank cell for unknown text."""
    return _COMPACT_GLYPHS.get(char.upper(), _COMPACT_GLYPHS[" "])


def _compact_text_width(text: str) -> int:
    """Return the compact display glyph width for ``text``."""
    width = 0
    for char in text:
        if width:
            width += _COMPACT_GAP_PIXELS
        pattern = _compact_glyph(char)
        width += len(pattern[0])
    return width


def _draw_compact_glyph(frame: object, pattern: tuple, x0: int, y0: int) -> None:
    """Draw one compact display glyph into ``frame``."""
    for y, row in enumerate(pattern):
        dy = y0 + y
        if dy < 0 or dy >= frame.height:
            continue
        for x, bit in enumerate(row):
            dx = x0 + x
            if bit == "1" and 0 <= dx < frame.width:
                frame.data[(dy * frame.width + dx) * frame.channels] = _COMPACT_ON


def _draw_compact_text(
    frame: object,
    text: str,
    row_index: int,
    *,
    colon_visible: bool = True,
    y_offset: int = 0,
) -> None:
    """Draw compact text centered inside one matrix row band."""
    x0 = (frame.width - _compact_text_width(text)) // 2
    y0 = row_index * _CLOCK_ROW_HEIGHT
    y0 += (_CLOCK_ROW_HEIGHT - _COMPACT_GLYPH_HEIGHT) // 2
    y0 += y_offset
    for char in text:
        pattern = _compact_glyph(char)
        if char != ":" or colon_visible:
            _draw_compact_glyph(frame, pattern, x0, y0)
        x0 += len(pattern[0]) + _COMPACT_GAP_PIXELS


def _clock_face_frame(top: str, bottom: str, *, colon_visible: bool) -> object:
    """Render compact clock time above a compact month-name date."""
    frame = Frame.blank(_DISPLAY_WIDTH_PIXELS, _DISPLAY_HEIGHT_PIXELS)
    _draw_compact_text(frame, top, 0, colon_visible=colon_visible)
    _draw_compact_text(frame, bottom, 1, y_offset=_CLOCK_BOTTOM_Y_OFFSET)
    return frame


def _display_frame(top: str, bottom: str, *, colon_visible: bool) -> object:
    """Render waiting text or the fitted clock face."""
    if ":" in top:
        return _clock_face_frame(top, bottom, colon_visible=colon_visible)
    return Frame.text_lines((top, bottom))


def _show(
    display: object,
    state: dict,
    top: str,
    bottom: str,
    *,
    colon_visible: bool,
) -> None:
    """Refresh the display only when text changes; otherwise periodically heal it."""
    lines = (top, bottom, colon_visible)
    now = time.ticks_ms()
    if state.get("shown") != lines:
        display.show(_display_frame(top, bottom, colon_visible=colon_visible))
        state["shown"] = lines
        state["last_reassert_ms"] = now
        return
    last_reassert = state.get("last_reassert_ms")
    if last_reassert is None or time.ticks_diff(now, last_reassert) >= _REASSERT_MS:
        display.show(_display_frame(top, bottom, colon_visible=colon_visible))
        state["last_reassert_ms"] = now


def _refresh_display(display: object, rtc: object, state: dict) -> None:
    """Render waiting text or the current RTC-backed clock face."""
    top, bottom, colon_visible = _display_lines(
        rtc,
        synced=bool(state.get("synced")),
    )
    _show(display, state, top, bottom, colon_visible=colon_visible)


def _sync_from_line(line: str | None, rtc: object, state: dict) -> None:
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
    local = local_from_gps(cached_date, utc_time, state["lat"], state["lon"])
    offset_s, tz_abbrev = offset_seconds_from_gps(
        cached_date,
        utc_time,
        state["lat"],
        state["lon"],
    )
    rtc.datetime(_rtc_datetime(local))
    state["synced"] = True
    emit(
        {
            "fix": True,
            "lat": state["lat"],
            "lon": state["lon"],
            "offset_h": offset_s // 3600,
            "offset_min": offset_s // 60,
            "tz": tz_abbrev,
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
