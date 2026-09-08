"""Shared fakes and frame inspection helpers for the clock firmware tests.

The firmware talks to four collaborators: a display (``show``/``flip``), a GPS
(``readline``), an RTC (``datetime``), and a ``time``-like clock. Each is faked
here so tests drive the async loops deterministically, with no wall-clock waits.
"""

from __future__ import annotations


class StopLoop(BaseException):
    """Sentinel that escapes the firmware's ``except Exception`` guards.

    Derives from BaseException so ``guarded_program`` and ``main``'s init retry
    cannot swallow it, letting a test end an otherwise-infinite loop.
    """


class ManualTime:
    """``time`` stub whose monotonic tick counter is advanced by the test."""

    def __init__(self) -> None:
        """Start the counter at zero."""
        self.ticks = 0

    def ticks_ms(self) -> int:
        """Return the current tick without advancing it."""
        return self.ticks

    def ticks_diff(self, newer: int, older: int) -> int:
        """Return the difference between two tick values."""
        return newer - older

    def advance(self, ms: int) -> int:
        """Move the clock forward and return the new tick."""
        self.ticks += ms
        return self.ticks


class AdvancingTime(ManualTime):
    """Clock that moves forward on every reading.

    Lets the step coroutines' wall-clock deadlines expire without any real
    waiting, so a 3-minute screen hold completes in a handful of iterations.
    """

    def __init__(self, step_ms: int = 1_000) -> None:
        """Store how far each reading advances the clock."""
        super().__init__()
        self._step_ms = step_ms

    def ticks_ms(self) -> int:
        """Return the current tick, then advance it."""
        now = self.ticks
        self.ticks += self._step_ms
        return now


class CountdownTime(ManualTime):
    """``ManualTime`` that raises :class:`StopLoop` after ``stop_after`` sleeps."""

    def __init__(self, stop_after: int, *, step_ms: int = 1) -> None:
        """Store the sleep budget and the per-sleep tick step."""
        super().__init__()
        self._stop = stop_after
        self._step_ms = step_ms
        self.sleeps = 0

    def sleep_ms(self, _ms: int) -> None:
        """Advance the clock, then stop the loop once the budget is spent."""
        self.sleeps += 1
        self.advance(self._step_ms)
        if self.sleeps >= self._stop:
            raise StopLoop


class FakeDisplay:
    """Display stand-in recording rendered frames and orientation flips."""

    def __init__(self, width_pixels: int = 32, height_pixels: int = 16) -> None:
        """Declare the panel geometry the engine renders into, with an empty call log."""
        self.width_pixels = width_pixels
        self.height_pixels = height_pixels
        self.shown: list[object] = []
        self.flips = 0

    def show(self, frame: object) -> None:
        """Record the requested frame."""
        self.shown.append(frame)

    def flip(self) -> None:
        """Record a display-orientation flip."""
        self.flips += 1


class FakeGPS:
    """GPS stand-in returning scripted lines or raising scripted exceptions."""

    def __init__(self, lines: list | None = None) -> None:
        """Store scripted readline outcomes."""
        self._lines = list(lines or [])

    def readline(self) -> str | None:
        """Return the next scripted line, or None when exhausted."""
        if not self._lines:
            return None
        line = self._lines.pop(0)
        if isinstance(line, Exception):
            raise line
        return line


class FakeRTC:
    """RTC stand-in supporting MicroPython's datetime getter/setter shape."""

    def __init__(self, value: tuple = (2026, 1, 1, 3, 0, 0, 0, 0)) -> None:
        """Start at a deterministic instant."""
        self.value = value

    def datetime(self, value: tuple | None = None) -> tuple | None:
        """Get or set the stored RTC datetime tuple."""
        if value is None:
            return self.value
        self.value = tuple(value)
        return None


class FakeRandom:
    """Deterministic ``getrandbits`` source for screen and effect choices."""

    def __init__(self, values: list[int]) -> None:
        """Store the scripted random values, which cycle once exhausted."""
        self._values = list(values)
        self._index = 0

    def getrandbits(self, _bits: int) -> int:
        """Return the next scripted value, wrapping around the script."""
        value = self._values[self._index % len(self._values)]
        self._index += 1
        return value


def same_frame(left: object, right: object) -> bool:
    """Return whether two frames hold identical pixels."""
    if (left.width, left.height) != (right.width, right.height):
        return False
    return all(
        left.value_at(x, y) == right.value_at(x, y)
        for y in range(left.height)
        for x in range(left.width)
    )


def lit_pixels(frame: object, y0: int = 0, y1: int | None = None) -> set:
    """Return the ``(x, y)`` coordinates of every lit pixel in a row band.

    The band defaults to the whole frame; pass ``y0``/``y1`` to compare one text
    row of a two-row screen without the other row's pixels muddying the result.
    """
    if y1 is None:
        y1 = frame.height
    return {(x, y) for y in range(y0, y1) for x in range(frame.width) if frame.value_at(x, y)}


def lit_count(frame: object) -> int:
    """Return the number of lit pixels in a frame."""
    return len(lit_pixels(frame))


def lit_row(frame: object, y: int) -> int:
    """Return the number of lit pixels in one frame row."""
    return sum(1 for x in range(frame.width) if frame.value_at(x, y))


def lit_bounds(frame: object, y0: int, y1: int) -> tuple:
    """Return inclusive ``(left, right, top, bottom)`` lit bounds in a row band."""
    xs = []
    ys = []
    for y in range(y0, y1):
        for x in range(frame.width):
            if frame.value_at(x, y):
                xs.append(x)
                ys.append(y)
    return min(xs), max(xs), min(ys), max(ys)
