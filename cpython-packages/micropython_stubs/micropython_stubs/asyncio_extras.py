"""MicroPython-only `asyncio` names for host tests.

MicroPython's `asyncio` adds `ThreadSafeFlag`, `wait_for_ms`, and `sleep_ms`
to the subset it shares with CPython, and declares its own `TimeoutError`
where CPython aliases the built-in. Those extras cannot ship as a top-level
replacement module the way `machine` and `utime` do, because the stdlib
`asyncio` package already owns that name and wins on `sys.path`. Tests install
them onto the real module instead, and monkeypatch removes them afterwards::

    from micropython_stubs import asyncio_extras

    @pytest.fixture(autouse=True)
    def _micropython_asyncio(monkeypatch):
        asyncio_extras.install(monkeypatch)
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from typing import Any

import pytest


class AsyncioTimeoutError(Exception):
    """Host stand-in for MicroPython's `asyncio.TimeoutError`.

    MicroPython's class is unrelated to the built-in that CPython aliases, so a
    distinct host class prevents tests from accepting the wrong exception.
    """


class ThreadSafeFlag:
    """Host stand-in for MicroPython's `asyncio.ThreadSafeFlag`.

    A `set()` latches until a waiter consumes it, so an interrupt handler that
    fires before its reader awaits still wakes that reader exactly once —
    the property drivers rely on. `asyncio.Event` provides that latch; the
    interrupt-safety the real class adds is meaningless in a single-threaded
    test, and the one-waiter rule is left to the driver to enforce.
    """

    def __init__(self) -> None:
        """Create the flag in its cleared state."""
        self._event = asyncio.Event()

    def set(self) -> None:
        """Latch the flag, waking a waiter now or on its next wait()."""
        self._event.set()

    def clear(self) -> None:
        """Discard a latched set()."""
        self._event.clear()

    async def wait(self) -> None:
        """Wait for a set() and consume it."""
        await self._event.wait()
        self._event.clear()


async def wait_for_ms(awaitable: Awaitable[Any], timeout_ms: int) -> Any:
    """Await `awaitable`, raising `AsyncioTimeoutError` once `timeout_ms` expires.

    The timeout runs on real time, since it is usually the behaviour under
    test; a driver whose budget would stall a suite is better patched at its
    own timeout constant.

    Args:
        awaitable: Coroutine or future to await.
        timeout_ms: Millisecond budget before the wait is abandoned.

    Returns:
        Whatever `awaitable` returned.

    Raises:
        AsyncioTimeoutError: The budget expired.
    """
    try:
        return await asyncio.wait_for(awaitable, timeout_ms / 1000)
    except TimeoutError:
        raise AsyncioTimeoutError from None


async def sleep_ms(ms: int) -> None:  # noqa: ARG001 - firmware pacing, not behaviour under test.
    """Yield to the event loop without sleeping, mirroring `utime.sleep_ms`."""
    await asyncio.sleep(0)


def install(monkeypatch: pytest.MonkeyPatch) -> None:
    """Add the MicroPython-only names to the stdlib `asyncio` module.

    Firmware code reads them off `asyncio` when it runs, not when it is
    imported, so installing them after the import under test still works.

    Args:
        monkeypatch: Fixture that removes the names again after the test.
    """
    monkeypatch.setattr(asyncio, "ThreadSafeFlag", ThreadSafeFlag, raising=False)
    monkeypatch.setattr(asyncio, "TimeoutError", AsyncioTimeoutError, raising=False)
    monkeypatch.setattr(asyncio, "wait_for_ms", wait_for_ms, raising=False)
    monkeypatch.setattr(asyncio, "sleep_ms", sleep_ms, raising=False)
