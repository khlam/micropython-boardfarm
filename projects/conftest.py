"""Shared pytest fixtures for all project test suites.

Defines the time and status stubs used by every project's `main_ns` fixture
and full-import smoke tests. Individual project conftest files inject these
via the `fake_time` and `fake_status` fixture parameters.
"""

from collections.abc import Callable

import pytest


class _FakeTime:
    """time stub: monotonic ticks_ms counter and no-op sleep_ms."""

    def __init__(self) -> None:
        self.ticks = 0

    def ticks_ms(self) -> int:
        self.ticks += 1
        return self.ticks

    def sleep_ms(self, _ms: int) -> None:
        return None


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
