"""MCU MicroPython firmware for the clock project.

Reads UTC date/time and longitude from an ATGM336H GPS over UART, derives a
fixed local offset from longitude, sets the onboard RTC, and shows the selected
local clock screens on the 16x32 MAX7219 matrix.
"""

import os
import random
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
_DISPLAY_INTENSITY_LIMIT = 0.1

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
_SCREEN_HOLD_MS = 180_000
_SEASON_HOLD_MS = 3_000
_TRANSITION_STEPS = 20
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
    "W": (
        "10001",
        "10001",
        "10001",
        "10001",
        "10101",
        "11011",
        "10001",
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
_MONTH_ABBRS = (
    "JAN",
    "FEB",
    "MARCH",
    "APRIL",
    "MAY",
    "JUNE",
    "JULY",
    "AUG",
    "SEPT",
    "OCT",
    "NOV",
    "DEC",
)
_MONTH_NAMES = (
    "JANUARY",
    "FEBRUARY",
    "MARCH",
    "APRIL",
    "MAY",
    "JUNE",
    "JULY",
    "AUGUST",
    "SEPTEMBER",
    "OCTOBER",
    "NOVEMBER",
    "DECEMBER",
)
_DAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
_SEASON_WINTER = "WINTER"
_SEASONS = (
    _SEASON_WINTER,
    _SEASON_WINTER,
    "SPRING",
    "SPRING",
    "SPRING",
    "SUMMER",
    "SUMMER",
    "SUMMER",
    "AUTUMN",
    "AUTUMN",
    "AUTUMN",
    _SEASON_WINTER,
)
_SCREEN_MAIN = 0
_SCREEN_SEASON = 1
_SCREEN_TIME_SECONDS = 2
_SCREEN_FULL_DATE = 3
_SCREENS = (
    _SCREEN_MAIN,
    _SCREEN_TIME_SECONDS,
)
_INTERSTITIALS = (
    _SCREEN_SEASON,
    _SCREEN_FULL_DATE,
)
_TRANSITION_WIPE = 0
_TRANSITION_FADE = 1
_TRANSITION_SCROLL = 2
_TRANSITIONS = (
    _TRANSITION_WIPE,
    _TRANSITION_FADE,
    _TRANSITION_SCROLL,
)


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


def _format_time_parts(hour: int, minute: int) -> tuple:
    """Return a 12-hour clock string and meridiem label."""
    display_hour = hour % 12
    if display_hour == 0:
        display_hour = 12
    meridiem = "AM" if hour < 12 else "PM"
    return f"{display_hour}:{minute:02d}", meridiem


def _format_time_seconds(hour: int, minute: int, second: int) -> str:
    """Format a 24-hour clock value as 12-hour time with seconds."""
    clock, _meridiem = _format_time_parts(hour, minute)
    return f"{clock}:{second:02d}"


def _format_month_abbr(month: int) -> str:
    """Return the fixed-width month abbreviation for the display cycle."""
    return _MONTH_ABBRS[month - 1]


def _season_name(month: int) -> str:
    """Return the meteorological season name for ``month``."""
    return _SEASONS[month - 1]


def _compact_glyph(char: str) -> tuple:
    """Return a compact display glyph, using a blank cell for unknown text."""
    return _COMPACT_GLYPHS.get(char.upper(), _COMPACT_GLYPHS[" "])


def _compact_text_width(text: str, gap_pixels: int = _COMPACT_GAP_PIXELS) -> int:
    """Return the compact display glyph width for ``text``."""
    width = 0
    for char in text:
        if width:
            width += gap_pixels
        pattern = _compact_glyph(char)
        width += len(pattern[0])
    return width


def _draw_compact_glyph(
    frame: object,
    pattern: tuple,
    x0: int,
    y0: int,
    intensity: int = _COMPACT_ON,
) -> None:
    """Draw one compact display glyph into ``frame``."""
    for y, row in enumerate(pattern):
        dy = y0 + y
        if dy < 0 or dy >= frame.height:
            continue
        for x, bit in enumerate(row):
            dx = x0 + x
            if bit == "1" and 0 <= dx < frame.width:
                frame.data[(dy * frame.width + dx) * frame.channels] = intensity


def _draw_compact_text_at(
    frame: object,
    text: str,
    x0: int,
    y0: int,
    *,
    gap_pixels: int = _COMPACT_GAP_PIXELS,
    colon_visible: bool = True,
    intensity: int = _COMPACT_ON,
) -> None:
    """Draw compact text at an exact origin."""
    for char in text:
        pattern = _compact_glyph(char)
        if char != ":" or colon_visible:
            _draw_compact_glyph(frame, pattern, x0, y0, intensity)
        x0 += len(pattern[0]) + gap_pixels


def _draw_compact_text_in_box(
    frame: object,
    text: str,
    x0: int,
    y0: int,
    width: int,
    height: int,
    *,
    gap_pixels: int = _COMPACT_GAP_PIXELS,
    y_offset: int = 0,
) -> None:
    """Draw compact text centered in a clipped rectangular display area."""
    text_width = _compact_text_width(text, gap_pixels)
    tx = x0 + (width - text_width) // 2
    ty = y0 + (height - _COMPACT_GLYPH_HEIGHT) // 2 + y_offset
    _draw_compact_text_at(frame, text, tx, ty, gap_pixels=gap_pixels)


def _draw_compact_text(
    frame: object,
    text: str,
    row_index: int,
    *,
    colon_visible: bool = True,
    y_offset: int = 0,
) -> None:
    """Draw compact text centered inside one matrix row band."""
    width = frame.width
    height = _CLOCK_ROW_HEIGHT
    text_width = _compact_text_width(text, _COMPACT_GAP_PIXELS)
    tx = (width - text_width) // 2
    ty = row_index * height + (height - _COMPACT_GLYPH_HEIGHT) // 2 + y_offset
    _draw_compact_text_at(frame, text, tx, ty, colon_visible=colon_visible)


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


def _wait_frame() -> object:
    """Render the unsynced GPS wait screen."""
    return _display_frame(_WAIT_TOP, _WAIT_BOT, colon_visible=True)


def _rtc_parts(rtc: object) -> tuple:
    """Return the RTC tuple fields used by the display manager."""
    year, month, day, weekday, hour, minute, second, _subsecond = rtc.datetime()
    return year, month, day, weekday, hour, minute, second


def _main_screen_frame(parts: tuple) -> object:
    """Render time with meridiem above month and day, both centered."""
    _year, month, day, _weekday, hour, minute, _second = parts
    clock, meridiem = _format_time_parts(hour, minute)
    frame = Frame.blank(_DISPLAY_WIDTH_PIXELS, _DISPLAY_HEIGHT_PIXELS)
    _draw_compact_text_in_box(
        frame,
        f"{clock} {meridiem}",
        0,
        0,
        _DISPLAY_WIDTH_PIXELS,
        8,
    )
    _draw_compact_text_in_box(
        frame,
        f"{_format_month_abbr(month)} {day}",
        0,
        8,
        _DISPLAY_WIDTH_PIXELS,
        8,
        y_offset=1,
    )
    return frame


def _season_screen_frame(parts: tuple) -> object:
    """Render the current meteorological season above the four-digit year."""
    year, month, _day, _weekday, _hour, _minute, _second = parts
    frame = Frame.blank(_DISPLAY_WIDTH_PIXELS, _DISPLAY_HEIGHT_PIXELS)
    _draw_compact_text_in_box(
        frame,
        _season_name(month),
        0,
        0,
        _DISPLAY_WIDTH_PIXELS,
        8,
    )
    _draw_compact_text_in_box(
        frame,
        f"{year:04d}",
        0,
        8,
        _DISPLAY_WIDTH_PIXELS,
        8,
        y_offset=1,
    )
    return frame


def _time_seconds_screen_frame(parts: tuple) -> object:
    """Render large 12-hour time with seconds and meridiem."""
    _year, _month, _day, _weekday, hour, minute, second = parts
    _clock, meridiem = _format_time_parts(hour, minute)
    frame = Frame.blank(_DISPLAY_WIDTH_PIXELS, _DISPLAY_HEIGHT_PIXELS)
    _draw_compact_text_in_box(
        frame,
        _format_time_seconds(hour, minute, second),
        0,
        0,
        _DISPLAY_WIDTH_PIXELS,
        8,
    )
    _draw_compact_text_in_box(
        frame,
        meridiem,
        0,
        8,
        _DISPLAY_WIDTH_PIXELS,
        8,
        y_offset=1,
    )
    return frame


def _full_date_screen_frame(parts: tuple) -> object:
    """Render the day of the week above the full month name."""
    _year, month, _day, weekday, _hour, _minute, _second = parts
    frame = Frame.blank(_DISPLAY_WIDTH_PIXELS, _DISPLAY_HEIGHT_PIXELS)
    _draw_compact_text_in_box(
        frame,
        _DAYS[weekday],
        0,
        0,
        _DISPLAY_WIDTH_PIXELS,
        8,
    )
    _draw_compact_text_in_box(
        frame,
        _MONTH_NAMES[month - 1],
        0,
        8,
        _DISPLAY_WIDTH_PIXELS,
        8,
        y_offset=1,
    )
    return frame


def _screen_frame(screen: int, rtc: object) -> object:
    """Render one display-cycle screen from the current RTC value."""
    parts = _rtc_parts(rtc)
    if screen == _SCREEN_SEASON:
        return _season_screen_frame(parts)
    if screen == _SCREEN_TIME_SECONDS:
        return _time_seconds_screen_frame(parts)
    if screen == _SCREEN_FULL_DATE:
        return _full_date_screen_frame(parts)
    return _main_screen_frame(parts)


def _screen_key(screen: int, rtc: object) -> tuple:
    """Return the visible-content key for one screen."""
    year, month, day, weekday, hour, minute, second = _rtc_parts(rtc)
    if screen == _SCREEN_SEASON:
        return screen, year, _season_name(month)
    if screen == _SCREEN_TIME_SECONDS:
        return screen, hour, minute, second
    if screen == _SCREEN_FULL_DATE:
        return screen, month, _DAYS[weekday]
    return screen, year, month, day, hour, minute


def _copy_frame(frame: object) -> object:
    """Return a byte-for-byte copy of ``frame``."""
    return Frame(frame.width, frame.height, frame.channels, bytearray(frame.data))


def _frame_value(frame: object, x: int, y: int, channel: int = 0) -> int:
    """Return one frame byte, clipping out-of-bounds reads to zero."""
    if x < 0 or y < 0 or x >= frame.width or y >= frame.height:
        return 0
    return frame.data[(y * frame.width + x) * frame.channels + channel]


def _set_frame_value(
    frame: object,
    x: int,
    y: int,
    value: int,
    channel: int = 0,
) -> None:
    """Set one frame byte when the coordinate is in bounds."""
    if 0 <= x < frame.width and 0 <= y < frame.height:
        frame.data[(y * frame.width + x) * frame.channels + channel] = value


def _max_frame_value(frame: object) -> int:
    """Return the maximum byte value present in ``frame``."""
    value = 0
    for item in frame.data:
        value = max(value, item)
    return value


def _min_visible_source_byte(intensity_limit: float) -> int:
    """Return the lowest source byte expected to survive display capping."""
    if intensity_limit <= 0:
        return 255
    capped_max = int(255 * intensity_limit + 0.5)
    if capped_max <= 0:
        return 255
    value = (255 + (2 * capped_max) - 1) // (2 * capped_max)
    if value < 1:
        return 1
    if value > 255:
        return 255
    return value


def _transition_pixel_value(
    source_value: int,
    step_value: int,
    min_visible: int,
) -> int:
    """Scale one lit transition pixel without dropping below visible range."""
    if source_value <= 0:
        return 0
    if source_value <= min_visible:
        return source_value
    step_value = max(step_value, min_visible)
    if step_value > source_value:
        return source_value
    return step_value


def _fade_step_value(
    max_value: int,
    progress: int,
    total: int,
    min_visible: int,
) -> int:
    """Return one global fade intensity between visible minimum and max."""
    if max_value <= 0:
        return 0
    if max_value <= min_visible:
        return max_value
    if progress <= 0:
        return min_visible
    if total <= 0 or progress >= total:
        return max_value
    return min_visible + ((max_value - min_visible) * progress // total)


def _dither_rank(x: int, y: int, total: int) -> int:
    """Return a stable spatial rank used by masked fade frames."""
    return ((x * 5) + (y * 3)) % total


def _masked_fade_frame(
    source: object,
    visible_steps: int,
    total_steps: int,
    step_value: int,
    min_visible: int,
) -> object:
    """Render a dither-masked view of ``source`` at one fade intensity."""
    frame = Frame.blank(source.width, source.height, source.channels)
    if visible_steps <= 0 or step_value <= 0:
        return frame
    visible_steps = min(total_steps, visible_steps)
    for y in range(source.height):
        for x in range(source.width):
            if _dither_rank(x, y, total_steps) >= visible_steps:
                continue
            for channel in range(source.channels):
                value = _frame_value(source, x, y, channel)
                value = _transition_pixel_value(value, step_value, min_visible)
                _set_frame_value(frame, x, y, value, channel)
    return frame


def _wipe_frame(source: object, target: object, step: int, steps: int) -> object:
    """Reveal ``target`` left-to-right over ``source``."""
    if step <= 0:
        return _copy_frame(source)
    if step >= steps:
        return _copy_frame(target)
    split = source.width * step // steps
    frame = Frame.blank(source.width, source.height, source.channels)
    for y in range(source.height):
        for x in range(source.width):
            active = target if x < split else source
            for channel in range(source.channels):
                _set_frame_value(
                    frame,
                    x,
                    y,
                    _frame_value(active, x, y, channel),
                    channel,
                )
    return frame


def _scroll_frame(source: object, target: object, step: int, steps: int) -> object:
    """Slide ``source`` left while ``target`` enters from the right."""
    if step <= 0:
        return _copy_frame(source)
    if step >= steps:
        return _copy_frame(target)
    offset = source.width * step // steps
    frame = Frame.blank(source.width, source.height, source.channels)
    for y in range(source.height):
        for x in range(source.width):
            src_x = x + offset
            dst_x = x - (source.width - offset)
            for channel in range(source.channels):
                value = _frame_value(source, src_x, y, channel)
                if value <= 0:
                    value = _frame_value(target, dst_x, y, channel)
                _set_frame_value(frame, x, y, value, channel)
    return frame


def _fade_frame(
    source: object,
    target: object,
    step: int,
    steps: int,
    intensity_limit: float,
) -> object:
    """Fade through masked low-intensity frames into ``target``."""
    if step <= 0:
        return _copy_frame(source)
    if step >= steps:
        return _copy_frame(target)
    min_visible = _min_visible_source_byte(intensity_limit)
    half = steps // 2
    if step <= half:
        visible_steps = half - step
        value = _fade_step_value(
            _max_frame_value(source),
            visible_steps - 1,
            half - 1,
            min_visible,
        )
        return _masked_fade_frame(source, visible_steps, half, value, min_visible)
    visible_steps = step - half
    total_steps = steps - half
    value = _fade_step_value(
        _max_frame_value(target),
        visible_steps - 1,
        total_steps - 1,
        min_visible,
    )
    return _masked_fade_frame(target, visible_steps, total_steps, value, min_visible)


def _transition_frame(transition: dict) -> object:
    """Render one transition frame from transition state."""
    effect = transition["effect"]
    source = transition["source"]
    target = transition["target"]
    step = transition["step"]
    steps = transition["steps"]
    if effect == _TRANSITION_FADE:
        return _fade_frame(source, target, step, steps, transition["intensity_limit"])
    if effect == _TRANSITION_SCROLL:
        return _scroll_frame(source, target, step, steps)
    return _wipe_frame(source, target, step, steps)


def _randbelow(limit: int, rng: object | None = None) -> int:
    """Return a random integer in ``range(limit)`` using a small MCU API."""
    if rng is None:
        rng = random
    return rng.getrandbits(8) % limit


def _choose_next_screen(current: int, rng: object | None = None) -> int:
    """Choose any screen except ``current``."""
    cur_idx = 0
    for i, s in enumerate(_SCREENS):
        if s == current:
            cur_idx = i
            break
    offset = _randbelow(len(_SCREENS) - 1, rng) + 1
    return _SCREENS[(cur_idx + offset) % len(_SCREENS)]


def _choose_transition(rng: object | None = None) -> int:
    """Choose one transition effect."""
    return _TRANSITIONS[_randbelow(len(_TRANSITIONS), rng)]


def _show_wait(display: object, state: dict) -> None:
    """Refresh the unsynced wait screen only when needed."""
    key = ("wait",)
    now = time.ticks_ms()
    if state.get("shown") != key:
        display.show(_wait_frame())
        state["shown"] = key
        state["last_reassert_ms"] = now
        return
    last_reassert = state.get("last_reassert_ms")
    if last_reassert is None or time.ticks_diff(now, last_reassert) >= _REASSERT_MS:
        display.show(_wait_frame())
        state["last_reassert_ms"] = now


def _start_screen_cycle(display: object, rtc: object, state: dict, now: int) -> None:
    """Start the synced display cycle on the main screen."""
    frame = _screen_frame(_SCREEN_MAIN, rtc)
    display.show(frame)
    state["shown"] = _screen_key(_SCREEN_MAIN, rtc)
    state["screen"] = _SCREEN_MAIN
    state["screen_frame"] = frame
    state["screen_started_ms"] = now
    state["last_reassert_ms"] = now
    state["transition"] = None


def _is_interstitial(screen: int) -> bool:
    """Return whether ``screen`` is a brief interstitial rather than a regular screen."""
    return screen in (_SCREEN_SEASON, _SCREEN_FULL_DATE)


def _choose_interstitial(rng: object | None = None) -> int:
    """Choose one interstitial screen at random."""
    return _INTERSTITIALS[_randbelow(len(_INTERSTITIALS), rng)]


def _start_transition(rtc: object, state: dict) -> None:
    """Create transition state for the next screen and effect.

    Regular screens transition to a random interstitial; interstitial
    screens transition to a random regular screen.
    """
    current = state.get("screen", _SCREEN_MAIN)
    if _is_interstitial(current):
        prev_regular = state.get("prev_regular", _SCREEN_MAIN)
        next_screen = _choose_next_screen(prev_regular)
    else:
        state["prev_regular"] = current
        next_screen = _choose_interstitial()
    target = _screen_frame(next_screen, rtc)
    source = state.get("screen_frame")
    if source is None:
        source = _screen_frame(current, rtc)
    state["transition"] = {
        "effect": _choose_transition(),
        "source": source,
        "target": target,
        "target_screen": next_screen,
        "target_key": _screen_key(next_screen, rtc),
        "step": 1,
        "steps": _TRANSITION_STEPS,
        "intensity_limit": state.get("intensity_limit", BOARD.display.intensity_limit),
    }


def _advance_transition(display: object, state: dict, now: int) -> None:
    """Render at most one active transition frame."""
    transition = state["transition"]
    frame = _transition_frame(transition)
    display.show(frame)
    state["last_reassert_ms"] = now
    if transition["step"] >= transition["steps"]:
        state["screen"] = transition["target_screen"]
        state["screen_frame"] = transition["target"]
        state["shown"] = transition["target_key"]
        state["screen_started_ms"] = now
        state["transition"] = None
        return
    transition["step"] += 1


def _refresh_current_screen(
    display: object,
    rtc: object,
    state: dict,
    now: int,
) -> None:
    """Refresh the active screen for live RTC changes or periodic healing."""
    screen = state.get("screen", _SCREEN_MAIN)
    key = _screen_key(screen, rtc)
    if state.get("shown") != key:
        frame = _screen_frame(screen, rtc)
        display.show(frame)
        state["screen_frame"] = frame
        state["shown"] = key
        state["last_reassert_ms"] = now
        return
    last_reassert = state.get("last_reassert_ms")
    if last_reassert is None or time.ticks_diff(now, last_reassert) >= _REASSERT_MS:
        frame = _screen_frame(screen, rtc)
        display.show(frame)
        state["screen_frame"] = frame
        state["last_reassert_ms"] = now


def _refresh_display(display: object, rtc: object, state: dict) -> None:
    """Render waiting text or advance the RTC-backed multi-screen cycle."""
    if not state.get("synced"):
        _show_wait(display, state)
        return
    now = time.ticks_ms()
    if "screen" not in state:
        _start_screen_cycle(display, rtc, state, now)
        return
    if state.get("transition") is not None:
        _advance_transition(display, state, now)
        return
    started = state.get("screen_started_ms", now)
    hold_ms = (
        _SEASON_HOLD_MS if _is_interstitial(state.get("screen", _SCREEN_MAIN)) else _SCREEN_HOLD_MS
    )
    if time.ticks_diff(now, started) >= hold_ms:
        _start_transition(rtc, state)
        _advance_transition(display, state, now)
        return
    _refresh_current_screen(display, rtc, state, now)


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
    state = {
        "synced": False,
        "intensity_limit": BOARD.display.intensity_limit,
    }
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
