"""Host CPython stub of MicroPython's `utime` module."""

import time as _time

# MicroPython's tick counter wraps at 2**30 ms.
_TICKS_PERIOD = 1 << 30
_HALF_TICKS_PERIOD = 1 << 29


def sleep_ms(ms: int) -> None:
    """Return immediately instead of sleeping."""


def ticks_ms() -> int:
    """Return a monotonic millisecond timestamp."""
    return int(_time.monotonic() * 1000)


def ticks_diff(a: int, b: int) -> int:
    """Return MicroPython's signed, wrap-safe tick difference `a - b`."""
    return (a - b + _HALF_TICKS_PERIOD) % _TICKS_PERIOD - _HALF_TICKS_PERIOD
