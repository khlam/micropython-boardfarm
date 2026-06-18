"""Display cycle for the 8x32 LED matrix clock.

Alternates two phases on a MAX7219 display, reading time from a ``machine.RTC``:

    TIME - 12-hour bold digits with a blinking colon and AM/PM   (5 s)
    DAY  - the current weekday name in the normal 5x7 font       (3 s)

Weekday names that overflow 32px (e.g. WEDNESDAY) wiggle side-to-side via
``show_auto``; shorter ones are centered.

Usage::

    cycle = DisplayCycle(display, rtc)
    cycle.start()
    while True:
        cycle.step()
        time.sleep_ms(10)
"""

import utime as _time
from micropython import const

from max7219.font_bold import char_cols as _bold
from max7219.font_bold import char_cols_tiny as _tiny

_MODE_TIME = const(0)
_MODE_DAY = const(1)

_COLON_MS = const(1000)
_TIME_MS = const(5000)
_DAY_MS = const(3000)
_WIGGLE_MS = const(120)

_NOON = const(12)

_DAY_NAMES = ("MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY")


def format_time_12h(hour24: int, minute: int, *, colon_on: bool) -> tuple:
    """Format a 24-hour time as a 12-hour display string with an AM/PM suffix.

    Args:
        hour24: Hour in 0-23.
        minute: Minute in 0-59.
        colon_on: When True the separator is ``":"``; when False it is a space,
            which produces the blinking-colon effect across calls.

    Returns:
        ``(time_text, suffix)`` e.g. ``("1:05", "PM")``. Hours are not
        zero-padded; minutes always are. Midnight is ``"12 ... AM"`` and noon is
        ``"12 ... PM"``.
    """
    suffix = "AM" if hour24 < _NOON else "PM"
    h = hour24 % _NOON
    if h == 0:
        h = _NOON
    sep = ":" if colon_on else " "
    return (f"{h}{sep}{minute:02d}", suffix)


def day_name(wd: int) -> str:
    """Return the uppercase weekday name for ``wd`` (0=Monday..6=Sunday)."""
    if wd < 0 or wd > 6:
        return "?"
    return _DAY_NAMES[wd]


def show_time(display: object, rtc: object, *, colon: bool = True) -> None:
    """Render the RTC time in bold 12-hour format with an AM/PM suffix.

    Args:
        display: A MAX7219 instance.
        rtc: A ``machine.RTC`` whose ``datetime()`` returns the 8-tuple
            ``(year, month, day, weekday, hour, minute, second, subsecond)``.
        colon: Passed through to ``format_time_12h`` for the blink effect.
    """
    dt = rtc.datetime()
    text, suffix = format_time_12h(dt[4], dt[5], colon_on=colon)
    display.show_time(text, suffix, _bold, _tiny)


class DisplayCycle:
    """Drives the TIME <-> DAY phase cycle on a MAX7219 from an RTC."""

    def __init__(self, display: object, rtc: object) -> None:
        """Store the display and RTC; ``start()`` begins the cycle.

        Args:
            display: A MAX7219 instance.
            rtc: A ``machine.RTC`` instance.
        """
        self._display = display
        self._rtc = rtc
        self._mode = _MODE_TIME
        self._mode_start = 0
        self._colon_tick = 0
        self._colon_on = True
        self._wiggle_tick = 0

    def start(self) -> None:
        """Begin the cycle from the TIME phase."""
        self._enter_time()

    def _enter_time(self) -> None:
        """Switch to the TIME phase and render it immediately."""
        now = _time.ticks_ms()
        self._mode = _MODE_TIME
        self._mode_start = now
        self._colon_tick = now
        self._colon_on = True
        show_time(self._display, self._rtc, colon=True)

    def _enter_day(self) -> None:
        """Switch to the DAY phase and render the weekday name."""
        now = _time.ticks_ms()
        self._mode = _MODE_DAY
        self._mode_start = now
        self._wiggle_tick = now
        dt = self._rtc.datetime()
        self._display.show_auto(day_name(dt[3]))

    def step(self) -> None:
        """Advance the cycle. Call roughly every 10 ms from the main loop."""
        now = _time.ticks_ms()
        if self._mode == _MODE_TIME:
            if _time.ticks_diff(now, self._colon_tick) >= _COLON_MS:
                self._colon_on = not self._colon_on
                self._colon_tick = now
                show_time(self._display, self._rtc, colon=self._colon_on)
            if _time.ticks_diff(now, self._mode_start) >= _TIME_MS:
                self._enter_day()
        else:  # _MODE_DAY
            if _time.ticks_diff(now, self._wiggle_tick) >= _WIGGLE_MS:
                self._wiggle_tick = now
                self._display.wiggle_step()
            if _time.ticks_diff(now, self._mode_start) >= _DAY_MS:
                self._enter_time()
