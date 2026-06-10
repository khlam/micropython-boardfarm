"""Shared pytest fixtures for all project test suites.

Defines the time and status stubs used by every project's `main_ns` fixture
and full-import smoke tests. Individual project conftest files inject these
via the `fake_time` and `fake_status` fixture parameters.
"""

from collections.abc import Callable

import pytest


class _FakeTime:
    """time stub: monotonic ticks_ms counter, ticks_diff, and no-op sleep_ms."""

    def __init__(self) -> None:
        self.ticks = 0

    def ticks_ms(self) -> int:
        """Return the next monotonic tick value (increments by 1)."""
        self.ticks += 1
        return self.ticks

    def ticks_diff(self, a: int, b: int) -> int:
        """Return the signed difference between two ticks_ms() snapshots."""
        return a - b

    def sleep_ms(self, _ms: int) -> None:
        """No-op sleep so tests run without delay."""
        return


class _FakeStatus:
    """status stub: record every transition call by name into self.calls."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __getattr__(self, name: str) -> Callable[[], None]:
        # Only intercept the public LED transitions; let dunder lookups fail
        # so pytest's own introspection is unaffected.
        if name.startswith("_"):
            raise AttributeError(name)

        def _rec() -> None:
            self.calls.append(name)

        return _rec


@pytest.fixture
def fake_time() -> _FakeTime:
    """Fresh _FakeTime instance for each test."""
    return _FakeTime()


@pytest.fixture
def fake_status() -> _FakeStatus:
    """Fresh _FakeStatus instance for each test."""
    return _FakeStatus()
