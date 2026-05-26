"""Host CPython stub of the `utime` module — sleep_ms is a no-op so tests never wait."""

import time as _time


def sleep_ms(ms: int) -> None:
    """No-op stand-in for `utime.sleep_ms`; tests never need to actually wait."""


def ticks_ms() -> int:
    """Return a monotonic millisecond timestamp."""
    return int(_time.monotonic() * 1000)


def ticks_diff(a: int, b: int) -> int:
    """Return `a - b`; mirrors MicroPython's `utime.ticks_diff` semantics."""
    return a - b
