"""Clock screen specifications and renderers."""

import random
from collections import namedtuple

from pixel_display import Canvas

from clock_text import (
    COMPACT_GLYPH_HEIGHT,
    COMPACT_ON,
    HEIGHT_PIXELS,
    WIDTH_PIXELS,
    blank_frame,
    compact_text_width,
    draw_compact_text_at,
    two_row_frame,
)

ScreenSpec = namedtuple("ScreenSpec", ("id", "name", "kind", "hold_ms", "render", "key"))

SCREEN_MAIN = 0
SCREEN_SEASON = 1
SCREEN_TIME_SECONDS = 2
SCREEN_FULL_DATE = 3
SCREEN_CLOCK_MERIDIEM = 4
WAIT_OFF = 5
WAIT_ON = 6

KIND_REGULAR = "regular"
KIND_INTERSTITIAL = "interstitial"
KIND_WAIT = "wait"

SCREEN_HOLD_MS = 180_000
INTERSTITIAL_HOLD_MS = 3_000
WAIT_ROTATE_MS = 1_000

CLOCK_MERIDIEM_TIME_X_SCALE = 2
CLOCK_MERIDIEM_TIME_Y_SCALE = 2
CLOCK_MERIDIEM_TIME_GAP_PIXELS = 0
CLOCK_MERIDIEM_LABEL_GAP_PIXELS = 1
CLOCK_MERIDIEM_LABEL_LINE_GAP_PIXELS = 1

MONTH_ABBRS = (
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
MONTH_NAMES = (
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
DAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")

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


def rtc_parts(rtc: object) -> tuple:
    """Return the RTC tuple fields used by the display manager."""
    year, month, day, weekday, hour, minute, second, _subsecond = rtc.datetime()
    return year, month, day, weekday, hour, minute, second


def format_time_parts(hour: int, minute: int) -> tuple:
    """Return a 12-hour clock string and meridiem label."""
    display_hour = hour % 12
    if display_hour == 0:
        display_hour = 12
    meridiem = "AM" if hour < 12 else "PM"
    return f"{display_hour}:{minute:02d}", meridiem


def format_time_seconds(hour: int, minute: int, second: int) -> str:
    """Format a 24-hour clock value as 12-hour time with seconds."""
    clock, _meridiem = format_time_parts(hour, minute)
    return f"{clock}:{second:02d}"


def format_month_abbr(month: int) -> str:
    """Return the fixed-width month abbreviation for the display cycle."""
    return MONTH_ABBRS[month - 1]


def season_name(month: int) -> str:
    """Return the meteorological season name for ``month``."""
    return _SEASONS[month - 1]


def main_screen_frame(parts: tuple) -> object:
    """Render time with meridiem above day name and day number, both centered."""
    _year, _month, day, weekday, hour, minute, _second = parts
    clock, meridiem = format_time_parts(hour, minute)
    return two_row_frame(f"{clock} {meridiem}", f"{DAYS[weekday]} {day}")


def season_screen_frame(parts: tuple) -> object:
    """Render the current meteorological season above the four-digit year."""
    year, month, _day, _weekday, _hour, _minute, _second = parts
    return two_row_frame(season_name(month), f"{year:04d}")


def time_seconds_screen_frame(parts: tuple) -> object:
    """Render large 12-hour time with seconds and meridiem."""
    _year, _month, _day, _weekday, hour, minute, second = parts
    _clock, meridiem = format_time_parts(hour, minute)
    return two_row_frame(format_time_seconds(hour, minute, second), meridiem)


def clock_meridiem_screen_frame(parts: tuple) -> object:
    """Render a centered time-only face with meridiem."""
    _year, _month, _day, _weekday, hour, minute, _second = parts
    clock, meridiem = format_time_parts(hour, minute)
    canvas = Canvas(WIDTH_PIXELS, HEIGHT_PIXELS, COMPACT_ON)
    clock_width = compact_text_width(
        clock,
        CLOCK_MERIDIEM_TIME_GAP_PIXELS,
        CLOCK_MERIDIEM_TIME_X_SCALE,
    )
    meridiem_width = 0
    for char in meridiem:
        meridiem_width = max(meridiem_width, compact_text_width(char, 0))
    meridiem_height = (len(meridiem) * COMPACT_GLYPH_HEIGHT) + (
        (len(meridiem) - 1) * CLOCK_MERIDIEM_LABEL_LINE_GAP_PIXELS
    )
    group_width = clock_width + CLOCK_MERIDIEM_LABEL_GAP_PIXELS + meridiem_width
    clock_x = (WIDTH_PIXELS - group_width) // 2
    clock_y = (HEIGHT_PIXELS - (COMPACT_GLYPH_HEIGHT * CLOCK_MERIDIEM_TIME_Y_SCALE)) // 2
    meridiem_x = clock_x + clock_width + CLOCK_MERIDIEM_LABEL_GAP_PIXELS
    meridiem_y = (HEIGHT_PIXELS - meridiem_height) // 2
    draw_compact_text_at(
        canvas,
        clock,
        clock_x,
        clock_y,
        gap_pixels=CLOCK_MERIDIEM_TIME_GAP_PIXELS,
        scale=(CLOCK_MERIDIEM_TIME_X_SCALE, CLOCK_MERIDIEM_TIME_Y_SCALE),
    )
    for char in meridiem:
        char_width = compact_text_width(char, 0)
        draw_compact_text_at(
            canvas,
            char,
            meridiem_x + ((meridiem_width - char_width) // 2),
            meridiem_y,
            gap_pixels=0,
        )
        meridiem_y += COMPACT_GLYPH_HEIGHT + CLOCK_MERIDIEM_LABEL_LINE_GAP_PIXELS
    return canvas.frame()


def full_date_screen_frame(parts: tuple) -> object:
    """Render the full month name with day number above the four-digit year."""
    year, month, day, _weekday, _hour, _minute, _second = parts
    return two_row_frame(f"{MONTH_NAMES[month - 1]} {day}", f"{year:04d}")


def wait_on_frame(_parts: tuple | None) -> object:
    """Render the visible GPS wait screen endpoint."""
    return two_row_frame("GPS", "WAIT")


def wait_off_frame(_parts: tuple | None) -> object:
    """Render the blank GPS wait screen endpoint."""
    return blank_frame()


def main_screen_key(parts: tuple) -> tuple:
    """Return the visible-content key for the compact time/date screen."""
    _year, _month, day, weekday, hour, minute, _second = parts
    return SCREEN_MAIN, weekday, day, hour, minute


def season_screen_key(parts: tuple) -> tuple:
    """Return the visible-content key for the season interstitial."""
    year, month, _day, _weekday, _hour, _minute, _second = parts
    return SCREEN_SEASON, year, season_name(month)


def time_seconds_screen_key(parts: tuple) -> tuple:
    """Return the visible-content key for the seconds screen."""
    _year, _month, _day, _weekday, hour, minute, second = parts
    return SCREEN_TIME_SECONDS, hour, minute, second


def full_date_screen_key(parts: tuple) -> tuple:
    """Return the visible-content key for the full-date interstitial."""
    year, month, day, _weekday, _hour, _minute, _second = parts
    return SCREEN_FULL_DATE, year, month, day


def clock_meridiem_screen_key(parts: tuple) -> tuple:
    """Return the visible-content key for the time-only screen."""
    _year, _month, _day, _weekday, hour, minute, _second = parts
    return SCREEN_CLOCK_MERIDIEM, hour, minute


def wait_on_key(_parts: tuple | None) -> tuple:
    """Return the visible-content key for the visible wait endpoint."""
    return (WAIT_ON,)


def wait_off_key(_parts: tuple | None) -> tuple:
    """Return the visible-content key for the blank wait endpoint."""
    return (WAIT_OFF,)


SCREEN_SPECS = (
    ScreenSpec(
        SCREEN_MAIN,
        "main",
        KIND_REGULAR,
        SCREEN_HOLD_MS,
        main_screen_frame,
        main_screen_key,
    ),
    ScreenSpec(
        SCREEN_CLOCK_MERIDIEM,
        "clock_meridiem",
        KIND_REGULAR,
        SCREEN_HOLD_MS,
        clock_meridiem_screen_frame,
        clock_meridiem_screen_key,
    ),
    ScreenSpec(
        SCREEN_TIME_SECONDS,
        "time_seconds",
        KIND_REGULAR,
        SCREEN_HOLD_MS,
        time_seconds_screen_frame,
        time_seconds_screen_key,
    ),
    ScreenSpec(
        SCREEN_SEASON,
        "season",
        KIND_INTERSTITIAL,
        INTERSTITIAL_HOLD_MS,
        season_screen_frame,
        season_screen_key,
    ),
    ScreenSpec(
        SCREEN_FULL_DATE,
        "full_date",
        KIND_INTERSTITIAL,
        INTERSTITIAL_HOLD_MS,
        full_date_screen_frame,
        full_date_screen_key,
    ),
    ScreenSpec(WAIT_OFF, "wait_off", KIND_WAIT, WAIT_ROTATE_MS, wait_off_frame, wait_off_key),
    ScreenSpec(WAIT_ON, "wait_on", KIND_WAIT, WAIT_ROTATE_MS, wait_on_frame, wait_on_key),
)

SCREEN_BY_ID = {spec.id: spec for spec in SCREEN_SPECS}
REGULAR_SCREENS = tuple(spec.id for spec in SCREEN_SPECS if spec.kind == KIND_REGULAR)
INTERSTITIAL_SCREENS = tuple(spec.id for spec in SCREEN_SPECS if spec.kind == KIND_INTERSTITIAL)
WAIT_SCREENS = (WAIT_OFF, WAIT_ON)


def screen_spec(screen: int) -> object:
    """Return the screen specification for ``screen``."""
    return SCREEN_BY_ID[screen]


def render_screen(screen: int, parts: tuple | None) -> object:
    """Render one screen from an RTC parts snapshot."""
    return screen_spec(screen).render(parts)


def screen_key(screen: int, parts: tuple | None) -> tuple:
    """Return the visible-content key for one screen."""
    return screen_spec(screen).key(parts)


def screen_frame(screen: int, rtc: object) -> object:
    """Render one display-cycle screen from the current RTC value."""
    return render_screen(screen, rtc_parts(rtc))


def key_from_rtc(screen: int, rtc: object) -> tuple:
    """Return the visible-content key for one screen from the RTC."""
    return screen_key(screen, rtc_parts(rtc))


def is_interstitial(screen: int) -> bool:
    """Return whether ``screen`` is a brief interstitial."""
    return screen_spec(screen).kind == KIND_INTERSTITIAL


def is_wait(screen: int) -> bool:
    """Return whether ``screen`` is a GPS wait endpoint."""
    return screen_spec(screen).kind == KIND_WAIT


def randbelow(limit: int, rng: object | None = None) -> int:
    """Return a random integer in ``range(limit)`` using a small MCU API."""
    if rng is None:
        rng = random
    return rng.getrandbits(8) % limit


def choose_next_regular(current: int, rng: object | None = None) -> int:
    """Choose any regular screen except ``current``."""
    cur_idx = 0
    for i, screen in enumerate(REGULAR_SCREENS):
        if screen == current:
            cur_idx = i
            break
    offset = randbelow(len(REGULAR_SCREENS) - 1, rng) + 1
    return REGULAR_SCREENS[(cur_idx + offset) % len(REGULAR_SCREENS)]


def choose_interstitial(rng: object | None = None) -> int:
    """Choose one interstitial screen at random."""
    return INTERSTITIAL_SCREENS[randbelow(len(INTERSTITIAL_SCREENS), rng)]
