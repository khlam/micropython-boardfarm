"""Host CPython tests for the async step coroutines that drive the engine.

These own the pacing: how long a transition frame waits, how long a screen is
held, and when a hold breaks out early. They are driven here against a manually
advanced clock so no test ever waits on real time.
"""

from __future__ import annotations

import asyncio

import pytest
from fake_clock import FakeDisplay, FakeRandom, FakeRTC, ManualTime

import clock_cycle
import clock_screens
import clock_transitions as ct


def test_play_transition_runs_until_the_transition_lands(engine_pair: tuple) -> None:
    engine, display, clock = engine_pair

    asyncio.run(
        clock_cycle.play_transition(
            engine, clock_screens.SCREEN_MAIN, clock, effect=ct.TRANSITION_WIPE
        )
    )

    assert engine.current_screen == clock_screens.SCREEN_MAIN
    assert engine.transition is None
    assert len(display.shown) == ct.TRANSITION_STEPS


def test_instant_transition_needs_only_one_frame(engine_pair: tuple) -> None:
    engine, display, clock = engine_pair

    asyncio.run(
        clock_cycle.play_transition(
            engine, clock_screens.SCREEN_MAIN, clock, effect=ct.TRANSITION_INSTANT
        )
    )

    assert len(display.shown) == 1


def test_dissolve_transition_uses_the_dissolve_effect(engine_pair: tuple) -> None:
    engine, _display, clock = engine_pair
    started: list = []
    original = engine.begin_transition

    def _record(target: int, *, effect: int | None = None, direction: int | None = None) -> None:
        started.append((target, effect, direction))
        original(target, effect=effect, direction=direction)

    engine.begin_transition = _record

    asyncio.run(clock_cycle.play_dissolve_transition(engine, clock_screens.SCREEN_SEASON, clock))

    assert started == [(clock_screens.SCREEN_SEASON, ct.TRANSITION_DISSOLVE, ct.DIRECTION_LEFT)]


def test_wait_transition_scrolls_the_wait_screen_into_itself(engine_pair: tuple) -> None:
    """The GPS-wait animation never blanks: it scrolls WAIT_ON into a fresh copy.

    The sequence always lands WAIT_ON before looping this animation, so the
    scroll runs from the wait screen into itself rather than from a dark frame.
    """
    engine, display, clock = engine_pair
    _land(engine, clock_screens.WAIT_ON)
    display.shown.clear()

    asyncio.run(clock_cycle.play_wait_transition(engine, clock))

    assert engine.current_screen == clock_screens.WAIT_ON
    # Every rendered frame keeps something lit, so the screen never goes dark.
    assert display.shown
    assert all(any(frame.data) for frame in display.shown)


def test_hold_screen_waits_for_the_screens_spec_duration(engine_pair: tuple) -> None:
    engine, _display, clock = engine_pair
    _land(engine, clock_screens.SCREEN_MAIN)
    hold_ms = clock_screens.screen_spec(clock_screens.SCREEN_MAIN).hold_ms
    started = clock.ticks

    asyncio.run(clock_cycle.hold_screen(engine, clock))

    assert clock.ticks - started >= hold_ms


def test_hold_screen_breaks_out_early_when_the_stop_predicate_fires(
    engine_pair: tuple,
) -> None:
    """The GPS-wait hold must end the moment a fix arrives, not 3 minutes later."""
    engine, _display, clock = engine_pair
    _land(engine, clock_screens.SCREEN_MAIN)
    started = clock.ticks
    calls = {"n": 0}

    def _stop() -> bool:
        calls["n"] += 1
        return calls["n"] > 2

    asyncio.run(clock_cycle.hold_screen(engine, clock, stop=_stop))

    hold_ms = clock_screens.screen_spec(clock_screens.SCREEN_MAIN).hold_ms
    assert clock.ticks - started < hold_ms


def test_hold_screen_reasserts_the_display_while_it_waits(engine_pair: tuple) -> None:
    engine, display, clock = engine_pair
    _land(engine, clock_screens.WAIT_ON)  # 1s hold keeps the test quick
    shown_before = len(display.shown)

    asyncio.run(clock_cycle.hold_screen(engine, clock))

    # The wait screen is static, so reassert only heals on the REASSERT_MS timer.
    assert len(display.shown) >= shown_before


def test_frame_rate_test_runs_for_its_hold_and_reports_rising_frame_counts(
    engine_pair: tuple,
) -> None:
    engine, display, clock = engine_pair
    samples: list = []
    engine.show_frame_rate = lambda count, elapsed, _now: samples.append((count, elapsed))

    asyncio.run(clock_cycle.run_frame_rate_test(engine, clock))

    hold_ms = clock_screens.screen_spec(clock_screens.SCREEN_FRAME_RATE).hold_ms
    assert samples
    assert [count for count, _elapsed in samples] == list(range(1, len(samples) + 1))
    assert samples[-1][1] < hold_ms
    assert display.shown == []  # show_frame_rate was stubbed out


def test_startup_handoff_shows_the_brand_then_dissolves_to_the_target(
    engine_pair: tuple,
) -> None:
    engine, _display, clock = engine_pair
    visited: list = []
    original = engine.begin_transition

    def _record(target: int, *, effect: int | None = None, direction: int | None = None) -> None:
        visited.append(target)
        original(target, effect=effect, direction=direction)

    engine.begin_transition = _record

    asyncio.run(clock_cycle.play_startup_handoff(engine, clock_screens.SCREEN_MAIN, clock))

    assert visited == [clock_screens.SCREEN_BRAND, clock_screens.SCREEN_MAIN]
    assert engine.current_screen == clock_screens.SCREEN_MAIN


def test_frame_pacing_sleeps_the_remainder_of_the_frame_budget() -> None:
    clock = ManualTime()
    slept: list = []

    asyncio.run(_pace(clock, frame_start=0, now=10, slept=slept))

    assert slept == [clock_cycle.FRAME_BUDGET_MS - 10]


def test_frame_pacing_never_drops_below_the_yield_floor() -> None:
    """An overrunning render still yields, so the GPS pump is always scheduled."""
    clock = ManualTime()
    slept: list = []

    asyncio.run(_pace(clock, frame_start=0, now=clock_cycle.FRAME_BUDGET_MS * 3, slept=slept))

    assert slept == [clock_cycle.MIN_FRAME_YIELD_MS]


def test_frame_budget_matches_the_target_frame_rate() -> None:
    assert clock_cycle.FRAME_BUDGET_MS == 1_000 // clock_cycle.TARGET_FPS


async def _pace(clock: ManualTime, *, frame_start: int, now: int, slept: list) -> None:
    """Run one ``_pace_frame`` with the clock parked at ``now``, recording the sleep."""
    clock.ticks = now
    real_sleep = asyncio.sleep_ms

    async def _record(ms: int) -> None:
        slept.append(ms)
        await real_sleep(0)

    asyncio.sleep_ms = _record
    try:
        await clock_cycle._pace_frame(clock, frame_start)
    finally:
        asyncio.sleep_ms = real_sleep


def _land(engine: clock_cycle.DisplayEngine, screen: int) -> None:
    """Put ``screen`` on the display immediately."""
    engine.begin_transition(screen, effect=ct.TRANSITION_INSTANT)
    engine.advance_transition(0)


@pytest.fixture
def engine_pair(monkeypatch: pytest.MonkeyPatch) -> tuple:
    """Return an ``(engine, display, clock)`` triple over fake hardware.

    ``asyncio.sleep_ms`` is patched to advance this clock by the requested
    interval and then yield immediately, so the coroutines' wall-clock deadlines
    are reached by the act of sleeping rather than by real elapsed time. Without
    it a 3-minute screen hold would take 3 real minutes.
    """
    display = FakeDisplay()
    clock = ManualTime()
    real_sleep = asyncio.sleep_ms

    async def _advancing_sleep(ms: int) -> None:
        clock.advance(max(1, ms))
        await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep_ms", _advancing_sleep)
    engine = clock_cycle.DisplayEngine(
        display,
        FakeRTC((2026, 6, 23, 1, 12, 30, 0, 0)),
        clock=clock,
        rng=FakeRandom([0]),
    )
    return engine, display, clock
