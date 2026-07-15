"""Host CPython stub of MicroPython's `utime` module."""

import time as _time


def sleep_ms(ms: int) -> None:
    """Return immediately instead of sleeping."""


def ticks_ms() -> int:
    """Return a monotonic millisecond timestamp."""
    return int(_time.monotonic() * 1000)


def ticks_diff(a: int, b: int) -> int:
    """Return `a - b`; mirrors MicroPython's `utime.ticks_diff` semantics."""
    return a - b
