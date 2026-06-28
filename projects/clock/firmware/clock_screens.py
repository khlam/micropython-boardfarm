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
SCREEN_FRAME_RATE = 5
SCREEN_BRAND = 6
WAIT_OFF = 7
WAIT_ON = 8
SCREEN_UPTIME = 9

KIND_REGULAR = "regular"
KIND_INTERSTITIAL = "interstitial"
KIND_DIAGNOSTIC = "diagnostic"
KIND_WAIT = "wait"

SCREEN_HOLD_MS = 180_000
INTERSTITIAL_HOLD_MS = 3_000
FRAME_RATE_TEST_MS = 15_000
BRAND_HOLD_MS = 1_500
WAIT_ROTATE_MS = 1_000
UPTIME_HOLD_MS = 7_000

# Marquee pacing for rows wider than the matrix: one pixel of travel every
# ``SCROLL_MS_PER_PX`` ms gives a slow, readable left-right sweep. Driven off the
# monotonic clock rather than a frame counter so the speed is wall-clock stable
# regardless of how often the hold loop reasserts.
SCROLL_MS_PER_PX = 100

CLOCK_MERIDIEM_LABEL_GAP_PIXELS = 1

WIDTH_PIXELS = 32
HEIGHT_PIXELS = 16

# Dedicated meridiem letterforms for the time-only face. The body font renders
# AM/PM as full-size glyphs with a chunky 5-wide ``M``; these condensed,
# uniform-width letters read as a tidy badge beside the scaled-up time and free
# a column for a slightly larger clock.
_MERIDIEM_GLYPH_WIDTH = 4
_MERIDIEM_GLYPH_HEIGHT = 7
_MERIDIEM_GLYPH_GAP = 1
_MERIDIEM_GLYPHS = {
    "A": ("0110", "1001", "1001", "1111", "1001", "1001", "1001"),
    "P": ("1110", "1001", "1001", "1110", "1000", "1000", "1000"),
    "M": ("1001", "1111", "1111", "1001", "1001", "1001", "1001"),
}

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
    """Render time with meridiem above day name and day number, both centered.

    The face shows no seconds, so the time colon blinks once per second and a
    seconds progress bar fills the gap row between the two text rows.
    """
    _year, _month, day, weekday, hour, minute, second = parts
    clock, meridiem = format_time_parts(hour, minute)
    frame = _two_row_frame(
        f"{clock} {meridiem}",
        f"{DAYS[weekday]} {day}",
        width_pixels,
        height_pixels,
        top_hidden_chars=_blink_colon_hidden(second),
    )
    _draw_seconds_bar(frame, second, (height_pixels // 2) - 1, width_pixels)
    return frame


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
    """Render a centered time-only face, scaling the time to fill the frame.

    The meridiem keeps a fixed narrow column on the right, drawn with the
    condensed clock-style badge font; the time then grows to the largest integer
    scale that fits the remaining box on each axis independently, so short
    strings (single-digit hour) render markedly larger than the widest
    ``12:59``-style times instead of leaving the screen mostly empty. The face
    shows no seconds, so the colon blinks once per second and a seconds progress
    bar fills the free bottom row.
    """
    _year, _month, _day, _weekday, hour, minute, second = parts
    clock, meridiem = format_time_parts(hour, minute)
    frame = Frame(width_pixels, height_pixels)
    label = _MeridiemBadge(meridiem)
    label_width, label_height = label.measure()
    base_width, base_height = Text(clock).measure()
    time_box_width = width_pixels - CLOCK_MERIDIEM_LABEL_GAP_PIXELS - label_width
    if base_width <= 0 or base_height <= 0 or time_box_width <= 0:
        frame[0:height_pixels, 0:width_pixels] = Text(f"{clock} {meridiem}")
        return frame
    x_scale = max(1, time_box_width // base_width)
    y_scale = max(1, height_pixels // base_height)
    time_text = Text(clock, scale=(x_scale, y_scale), hidden_chars=_blink_colon_hidden(second))
    time_width, time_height = time_text.measure()
    group_width = time_width + CLOCK_MERIDIEM_LABEL_GAP_PIXELS + label_width
    group_height = max(time_height, label_height)
    if group_width > width_pixels or group_height > height_pixels:
        frame[0:height_pixels, 0:width_pixels] = Text(f"{clock} {meridiem}")
        return frame
    x0 = (width_pixels - group_width) // 2
    time_x1 = x0 + time_width
    label_x0 = time_x1 + CLOCK_MERIDIEM_LABEL_GAP_PIXELS
    frame[0:height_pixels, x0:time_x1] = time_text
    frame[0:height_pixels, label_x0 : label_x0 + label_width] = label
    _draw_seconds_bar(frame, second, height_pixels - 1, width_pixels)
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


def frame_rate_screen_frame(
    parts: tuple | None,
    width_pixels: int = WIDTH_PIXELS,
    height_pixels: int = HEIGHT_PIXELS,
) -> object:
    """Render one display frame-rate diagnostic sample."""
    frame_index, _elapsed_ms, fps_x10 = _frame_rate_parts(parts)
    frame = Frame(width_pixels, height_pixels)
    split = max(1, height_pixels // 2)
    _draw_frame_rate_trace(frame, frame_index, width_pixels, split)
    if split < height_pixels:
        frame[split:height_pixels, 0:width_pixels] = Text(
            f"FPS {_frame_rate_label(fps_x10)}",
            valign="bottom",
        )
    return frame


def brand_screen_frame(
    _parts: tuple | None,
    width_pixels: int = WIDTH_PIXELS,
    height_pixels: int = HEIGHT_PIXELS,
) -> object:
    """Render the startup brand screen."""
    return _two_row_frame("KINHOLA", "M.COM", width_pixels, height_pixels)


def uptime_screen_frame(
    parts: tuple | None,
    width_pixels: int = WIDTH_PIXELS,
    height_pixels: int = HEIGHT_PIXELS,
) -> object:
    """Render the run uptime over the boot timestamp, scrolling rows that overflow.

    Top row reads ``UP HH:MM:SS`` (elapsed since the first GPS fix); bottom row
    reads ``BOOT: DD.MM.YY`` (the first fix's local date). Either row is wider
    than the matrix once labelled, so each scrolls independently as a slow
    left-right marquee when it does not fit.
    """
    boot_parts, now_parts, scroll_ms = _uptime_fields(parts)
    frame = Frame(width_pixels, height_pixels)
    split = height_pixels // 2
    top = "UP " + _format_uptime(_uptime_seconds(boot_parts, now_parts))
    bottom = "BOOT: " + _format_boot_date(boot_parts)
    if split <= 0:
        _draw_marquee_row(frame, top, 0, height_pixels, width_pixels, scroll_ms, "middle")
        return frame
    _draw_marquee_row(frame, top, 0, split, width_pixels, scroll_ms, "middle")
    _draw_marquee_row(
        frame, bottom, split, height_pixels - split, width_pixels, scroll_ms, "bottom"
    )
    return frame


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


def _two_row_frame(
    top: str,
    bottom: str,
    width_pixels: int,
    height_pixels: int,
    *,
    top_hidden_chars: str = "",
) -> object:
    """Render two centered text rows into an exact-size frame.

    ``top_hidden_chars`` are kept in the layout but drawn blank, letting the
    time colon blink without shifting the rest of the row.
    """
    frame = Frame(width_pixels, height_pixels)
    split = height_pixels // 2
    if split <= 0:
        frame[0:height_pixels, 0:width_pixels] = Text(top, hidden_chars=top_hidden_chars)
        return frame
    frame[0:split, 0:width_pixels] = Text(top, hidden_chars=top_hidden_chars)
    frame[split:height_pixels, 0:width_pixels] = Text(bottom, valign="bottom")
    return frame


def _blink_colon_hidden(second: int) -> str:
    """Return the chars to blank so the time colon blinks once per second."""
    return ":" if second % 2 else ""


def _draw_seconds_bar(frame: object, second: int, y: int, width: int) -> None:
    """Draw a left-anchored seconds progress bar that fills across the minute.

    The bar grows from empty at ``:00`` to the full width by ``:59``, giving a
    seconds readout on faces that only show hours and minutes. Drawing is
    skipped when the target row falls outside the frame.
    """
    if y < 0 or y >= frame.height:
        return
    filled = (second * width) // 59
    for x in range(filled):
        frame.pixel(x, y)


def _uptime_fields(parts: tuple | None) -> tuple:
    """Return the ``(boot_parts, now_parts, scroll_ms)`` triple the engine packs.

    The engine cannot express boot time or a scroll phase as an RTC snapshot, so
    it hands the uptime screen its own composite parts; ``None`` collapses to a
    no-fix, zero-phase placeholder.
    """
    if parts is None:
        return None, None, 0
    return parts


def _format_uptime(total_seconds: int) -> str:
    """Format an elapsed-seconds count as ``HH:MM:SS``, widening hours past 99."""
    hours = total_seconds // 3_600
    minutes = (total_seconds % 3_600) // 60
    seconds = total_seconds % 60
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def _format_boot_date(boot_parts: tuple | None) -> str:
    """Format the first-fix date as ``DD.MM.YY``, or dashes before any fix."""
    if boot_parts is None:
        return "--.--.--"
    year, month, day = boot_parts[0], boot_parts[1], boot_parts[2]
    return f"{day:02d}.{month:02d}.{year % 100:02d}"


def _uptime_seconds(boot_parts: tuple | None, now_parts: tuple | None) -> int:
    """Return whole seconds between the first fix and now, never negative."""
    if boot_parts is None or now_parts is None:
        return 0
    elapsed = _epoch_seconds(now_parts) - _epoch_seconds(boot_parts)
    return max(0, elapsed)


def _epoch_seconds(parts: tuple) -> int:
    """Return seconds since 1970-01-01 for an RTC parts tuple.

    Boot and now are both local RTC readings, so the shared epoch base cancels
    in the difference; the absolute value only needs to be consistent.
    """
    year, month, day, _weekday, hour, minute, second = parts
    return _days_from_civil(year, month, day) * 86_400 + hour * 3_600 + minute * 60 + second


def _days_from_civil(year: int, month: int, day: int) -> int:
    """Return days since 1970-01-01 (Hinnant's civil-to-days algorithm).

    Integer-only and branch-light so it runs the same on MicroPython as on the
    host; valid for any proleptic Gregorian date the RTC can hold.
    """
    y = year - (1 if month <= 2 else 0)
    era = (y if y >= 0 else y - 399) // 400
    yoe = y - era * 400
    doy = (153 * (month - 3 if month > 2 else month + 9) + 2) // 5 + (day - 1)
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    return era * 146_097 + doe - 719_468


def _scroll_offset(text_width: int, width_pixels: int, scroll_ms: int) -> int:
    """Return the left crop, in pixels, for a ping-pong marquee at ``scroll_ms``.

    Sweeps 0 -> overflow -> 0 as a triangle wave so the row eases to each edge
    and reverses instead of jumping back to the start.
    """
    overflow = text_width - width_pixels
    if overflow <= 0:
        return 0
    span = 2 * overflow
    phase = (scroll_ms // SCROLL_MS_PER_PX) % span
    return phase if phase <= overflow else span - phase


def _draw_marquee_row(
    frame: object,
    text: str,
    y0: int,
    band_height: int,
    width_pixels: int,
    scroll_ms: int,
    valign: str,
) -> None:
    """Draw one text row, centering it if it fits or scrolling it if it overflows.

    Overflowing text is rendered once into a full-width strip and a
    ``width_pixels`` window is blitted at the current scroll offset, since
    :class:`Text` refuses to draw content wider than its target box.
    """
    content = Text(text, valign=valign)
    text_width, _height = content.measure()
    if text_width <= width_pixels:
        frame[y0 : y0 + band_height, 0:width_pixels] = content
        return
    strip = Frame(text_width, band_height)
    strip[0:band_height, 0:text_width] = Text(text, align="left", valign=valign)
    offset = _scroll_offset(text_width, width_pixels, scroll_ms)
    for x in range(width_pixels):
        src_x = x + offset
        if src_x >= text_width:
            break
        for y in range(band_height):
            if strip.value_at(src_x, y):
                frame.pixel(x, y0 + y)


class _MeridiemBadge:
    """Condensed AM/PM badge drawn from the dedicated meridiem letterforms.

    Mirrors the :class:`Text` ``measure``/``draw`` interface so it can be
    assigned straight into a frame box, but stacks two uniform-width letters
    instead of reusing the body font's mixed-width glyphs.
    """

    def __init__(self, meridiem: str) -> None:
        """Store the two-letter meridiem to stack vertically."""
        self.letters = meridiem

    def measure(self) -> tuple:
        """Return the badge's pixel width and height."""
        count = len(self.letters)
        height = (count * _MERIDIEM_GLYPH_HEIGHT) + (max(0, count - 1) * _MERIDIEM_GLYPH_GAP)
        return _MERIDIEM_GLYPH_WIDTH, height

    def draw(self, frame: object, x0: int, y0: int, width: int, height: int) -> None:
        """Draw the stacked badge centered inside an assigned pixel box."""
        badge_width, badge_height = self.measure()
        if badge_width > width or badge_height > height:
            return
        x = x0 + ((width - badge_width) // 2)
        y = y0 + ((height - badge_height) // 2)
        for letter in self.letters:
            _draw_meridiem_glyph(frame, letter, x, y)
            y += _MERIDIEM_GLYPH_HEIGHT + _MERIDIEM_GLYPH_GAP


def _draw_meridiem_glyph(frame: object, letter: str, x0: int, y0: int) -> None:
    """Draw one meridiem letterform with its top-left corner at ``(x0, y0)``."""
    rows = _MERIDIEM_GLYPHS.get(letter)
    if rows is None:
        return
    for dy, row in enumerate(rows):
        for dx, bit in enumerate(row):
            if bit == "1":
                frame.pixel(x0 + dx, y0 + dy)


def _month_day_label(month: int, day: int, width_pixels: int, height_pixels: int) -> str:
    """Return the longest month/day label that fits the display width."""
    full = f"{MONTH_NAMES[month - 1]} {day}"
    if Text(full).fits(width_pixels, height_pixels):
        return full
    return f"{format_month_abbr(month)} {day}"


def _frame_rate_parts(parts: tuple | None) -> tuple:
    """Return checked frame-rate diagnostic values."""
    if parts is None or len(parts) != 3:
        return 0, 0, 0
    return parts


def _frame_rate_label(fps_x10: int) -> str:
    """Format a fixed-point frames-per-second value for the matrix."""
    fps_x10 = min(9_999, max(0, fps_x10))
    return f"{fps_x10 // 10}.{fps_x10 % 10}"


def _draw_frame_rate_trace(frame: object, frame_index: int, width: int, height: int) -> None:
    """Draw a moving diagnostic trace whose jumps reveal uneven frame pacing."""
    for x in range(width):
        frame.pixel(x, (x + frame_index) % height)
    head = frame_index % width
    trail = min(width, 5)
    for offset in range(trail):
        x = (head - offset) % width
        frame.pixel(x, 0)
        frame.pixel(x, height - 1)
        if offset < 2 and height > 2:
            frame.pixel(x, 1)
            frame.pixel(x, height - 2)


def main_screen_key(parts: tuple) -> tuple:
    """Return the visible-content key for the compact time/date screen.

    Includes ``second`` so the blinking colon and seconds bar re-render each
    second even while the hour and minute hold.
    """
    _year, _month, day, weekday, hour, minute, second = parts
    return SCREEN_MAIN, weekday, day, hour, minute, second


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
    """Return the visible-content key for the time-only screen.

    Includes ``second`` so the blinking colon and seconds bar re-render each
    second even while the hour and minute hold.
    """
    _year, _month, _day, _weekday, hour, minute, second = parts
    return SCREEN_CLOCK_MERIDIEM, hour, minute, second


def frame_rate_screen_key(parts: tuple | None) -> tuple:
    """Return the visible-content key for one frame-rate diagnostic sample."""
    frame_index, _elapsed_ms, fps_x10 = _frame_rate_parts(parts)
    return SCREEN_FRAME_RATE, frame_index, fps_x10


def brand_screen_key(_parts: tuple | None) -> tuple:
    """Return the visible-content key for the startup brand screen."""
    return (SCREEN_BRAND,)


def uptime_screen_key(parts: tuple | None) -> tuple:
    """Return the visible-content key for the uptime screen.

    Keys on both the whole-second uptime and the integer scroll step so the
    engine re-renders each tick of the clock *and* each pixel of marquee travel.
    """
    boot_parts, now_parts, scroll_ms = _uptime_fields(parts)
    return SCREEN_UPTIME, _uptime_seconds(boot_parts, now_parts), scroll_ms // SCROLL_MS_PER_PX


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
    ScreenSpec(
        SCREEN_UPTIME,
        "uptime",
        KIND_INTERSTITIAL,
        UPTIME_HOLD_MS,
        uptime_screen_frame,
        uptime_screen_key,
    ),
    ScreenSpec(
        SCREEN_FRAME_RATE,
        "frame_rate",
        KIND_DIAGNOSTIC,
        FRAME_RATE_TEST_MS,
        frame_rate_screen_frame,
        frame_rate_screen_key,
    ),
    ScreenSpec(
        SCREEN_BRAND,
        "brand",
        KIND_DIAGNOSTIC,
        BRAND_HOLD_MS,
        brand_screen_frame,
        brand_screen_key,
    ),
    ScreenSpec(WAIT_OFF, "wait_off", KIND_WAIT, WAIT_ROTATE_MS, wait_off_frame, wait_off_key),
    ScreenSpec(WAIT_ON, "wait_on", KIND_WAIT, WAIT_ROTATE_MS, wait_on_frame, wait_on_key),
)

SCREEN_BY_ID = {spec.id: spec for spec in SCREEN_SPECS}
REGULAR_SCREENS = tuple(spec.id for spec in SCREEN_SPECS if spec.kind == KIND_REGULAR)
INTERSTITIAL_SCREENS = tuple(spec.id for spec in SCREEN_SPECS if spec.kind == KIND_INTERSTITIAL)
DIAGNOSTIC_SCREENS = tuple(spec.id for spec in SCREEN_SPECS if spec.kind == KIND_DIAGNOSTIC)
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


def choose_regular(rng: object | None = None) -> int:
    """Choose one regular clock screen at random."""
    return REGULAR_SCREENS[randbelow(len(REGULAR_SCREENS), rng)]


def choose_interstitial(rng: object | None = None) -> int:
    """Choose one interstitial screen at random."""
    return INTERSTITIAL_SCREENS[randbelow(len(INTERSTITIAL_SCREENS), rng)]
