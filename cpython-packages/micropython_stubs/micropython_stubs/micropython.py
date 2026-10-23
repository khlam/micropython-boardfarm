"""Host CPython stub of MicroPython's `micropython` module."""


def const(x: int) -> int:
    """Return `x` unchanged."""
    return x


def schedule(func: object, arg: object) -> None:
    """Run `func(arg)` synchronously.

    On the device this queues `func` to run later in scheduler context; on the
    host the call is immediate, so tests see the deferred callback fire as soon
    as the interrupt/timer handler schedules it.
    """
    func(arg)
