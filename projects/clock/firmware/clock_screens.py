"""Clock screen specifications and renderers."""

import random
from collections import namedtuple

from pixel_frame import Frame, Text

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

CLOCK_MERIDIEM_TIME_X_SCALE = 1
CLOCK_MERIDIEM_TIME_Y_SCALE = 2
CLOCK_MERIDIEM_LABEL_GAP_PIXELS = 1

WIDTH_PIXELS = 32
HEIGHT_PIXELS = 16

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


def main_screen_frame(
    parts: tuple,
    width_pixels: int = WIDTH_PIXELS,
    height_pixels: int = HEIGHT_PIXELS,
) -> object:
    """Render time with meridiem above day name and day number, both centered."""
    _year, _month, day, weekday, hour, minute, _second = parts
    clock, meridiem = format_time_parts(hour, minute)
    return _two_row_frame(
        f"{clock} {meridiem}",
        f"{DAYS[weekday]} {day}",
        width_pixels,
        height_pixels,
    )


def season_screen_frame(
    parts: tuple,
    width_pixels: int = WIDTH_PIXELS,
    height_pixels: int = HEIGHT_PIXELS,
) -> object:
    """Render the current meteorological season above the four-digit year."""
    year, month, _day, _weekday, _hour, _minute, _second = parts
    return _two_row_frame(season_name(month), f"{year:04d}", width_pixels, height_pixels)


def time_seconds_screen_frame(
    parts: tuple,
    width_pixels: int = WIDTH_PIXELS,
    height_pixels: int = HEIGHT_PIXELS,
) -> object:
    """Render large 12-hour time with seconds and meridiem."""
    _year, _month, _day, _weekday, hour, minute, second = parts
    _clock, meridiem = format_time_parts(hour, minute)
    return _two_row_frame(
        format_time_seconds(hour, minute, second),
        meridiem,
        width_pixels,
        height_pixels,
    )


def clock_meridiem_screen_frame(
    parts: tuple,
    width_pixels: int = WIDTH_PIXELS,
    height_pixels: int = HEIGHT_PIXELS,
) -> object:
    """Render a centered time-only face with meridiem."""
    _year, _month, _day, _weekday, hour, minute, _second = parts
    clock, meridiem = format_time_parts(hour, minute)
    frame = Frame(width_pixels, height_pixels)
    time_text = Text(
        clock,
        scale=(CLOCK_MERIDIEM_TIME_X_SCALE, CLOCK_MERIDIEM_TIME_Y_SCALE),
    )
    label_text = Text(meridiem, flow="vertical")
    time_width, time_height = time_text.measure()
    label_width, label_height = label_text.measure()
    group_width = time_width + CLOCK_MERIDIEM_LABEL_GAP_PIXELS + label_width
    group_height = max(time_height, label_height)
    if group_width > width_pixels or group_height > height_pixels:
        frame[0:height_pixels, 0:width_pixels] = Text(f"{clock} {meridiem}")
        return frame
    x0 = (width_pixels - group_width) // 2
    time_x1 = x0 + time_width
    label_x0 = time_x1 + CLOCK_MERIDIEM_LABEL_GAP_PIXELS
    frame[0:height_pixels, x0:time_x1] = time_text
    frame[0:height_pixels, label_x0 : label_x0 + label_width] = label_text
    return frame


def full_date_screen_frame(
    parts: tuple,
    width_pixels: int = WIDTH_PIXELS,
    height_pixels: int = HEIGHT_PIXELS,
) -> object:
    """Render the full month name with day number above the four-digit year."""
    year, month, day, _weekday, _hour, _minute, _second = parts
    row_height = max(1, height_pixels // 2)
    return _two_row_frame(
        _month_day_label(month, day, width_pixels, row_height),
        f"{year:04d}",
        width_pixels,
        height_pixels,
    )


def wait_on_frame(
    _parts: tuple | None,
    width_pixels: int = WIDTH_PIXELS,
    height_pixels: int = HEIGHT_PIXELS,
) -> object:
    """Render the visible GPS wait screen endpoint."""
    return _two_row_frame("GPS", "WAIT", width_pixels, height_pixels)


def wait_off_frame(
    _parts: tuple | None,
    width_pixels: int = WIDTH_PIXELS,
    height_pixels: int = HEIGHT_PIXELS,
) -> object:
    """Render the blank GPS wait screen endpoint."""
    return Frame(width_pixels, height_pixels, intensity=0)


def _two_row_frame(top: str, bottom: str, width_pixels: int, height_pixels: int) -> object:
    """Render two centered text rows into an exact-size frame."""
    frame = Frame(width_pixels, height_pixels)
    split = height_pixels // 2
    if split <= 0:
        frame[0:height_pixels, 0:width_pixels] = Text(top)
        return frame
    frame[0:split, 0:width_pixels] = Text(top)
    frame[split:height_pixels, 0:width_pixels] = Text(bottom, valign="bottom")
    return frame


def _month_day_label(month: int, day: int, width_pixels: int, height_pixels: int) -> str:
    """Return the longest month/day label that fits the display width."""
    full = f"{MONTH_NAMES[month - 1]} {day}"
    if Text(full).fits(width_pixels, height_pixels):
        return full
    return f"{format_month_abbr(month)} {day}"


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


def render_screen(
    screen: int,
    parts: tuple | None,
    width_pixels: int = WIDTH_PIXELS,
    height_pixels: int = HEIGHT_PIXELS,
) -> object:
    """Render one screen from an RTC parts snapshot."""
    return screen_spec(screen).render(parts, width_pixels, height_pixels)


def screen_key(screen: int, parts: tuple | None) -> tuple:
    """Return the visible-content key for one screen."""
    return screen_spec(screen).key(parts)


def screen_frame(
    screen: int,
    rtc: object,
    width_pixels: int = WIDTH_PIXELS,
    height_pixels: int = HEIGHT_PIXELS,
) -> object:
    """Render one display-cycle screen from the current RTC value."""
    return render_screen(screen, rtc_parts(rtc), width_pixels, height_pixels)


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
