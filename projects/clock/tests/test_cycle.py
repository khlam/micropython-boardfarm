"""Host CPython tests for the display engine and the coroutines that drive it.

`clock_cycle` has two halves and this file follows the module's own order: the
`async` step coroutines that own pacing — how long a transition frame waits, how
long a screen is held, when a hold breaks out early — and then the
`DisplayEngine` state machine they step, which caches rendered frames per screen,
runs a transition between two snapshotted endpoints, and heals the panel when
content changes or the display drifts. Screen *order* lives in main.py and is
tested there.

Every test runs against a manually advanced clock, so none waits on real time.
"""

from __future__ import annotations

import asyncio
from itertools import pairwise
from types import SimpleNamespace
from unittest.mock import Mock

import machine
import pytest
from fake_clock import FakeDisplay, FakeRandom, ManualTime, same_frame

import clock_cycle
import clock_screens
import clock_sync
import clock_transitions as ct

_RTC_VALUE = (2026, 6, 23, 1, 12, 30, 0, 0)


# --------------------------------------------------------------------------
# Step coroutines: pacing, holds, and the startup sequence.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "effect,frames", [(ct.TRANSITION_INSTANT, 1), (ct.TRANSITION_WIPE, ct.TRANSITION_STEPS)]
)
def test_play_transition_runs_until_the_transition_lands(
    paced_engine: tuple, effect: int, frames: int
) -> None:
    engine, display, _clock = paced_engine

    asyncio.run(clock_cycle.play_transition(engine, clock_screens.SCREEN_MAIN, effect=effect))

    assert engine.current_screen == clock_screens.SCREEN_MAIN
    assert engine.transition is None
    assert len(display.shown) == frames


def test_dissolve_transition_lands_the_target_through_a_random_pixel_mask(
    paced_engine: tuple,
) -> None:
    """The dissolve helper forces its own effect rather than drawing one."""
    engine, display, _clock = paced_engine
    _land(engine, clock_screens.SCREEN_SEASON)
    display.shown.clear()

    asyncio.run(clock_cycle.play_dissolve_transition(engine, clock_screens.SCREEN_MAIN))

    assert engine.current_screen == clock_screens.SCREEN_MAIN
    assert len(display.shown) == ct.TRANSITION_STEPS
    assert same_frame(display.shown[-1], engine.screen_frame)
    # A dissolve reveals scattered pixels, so intermediate frames are neither
    # endpoint — that is what separates it from a wipe or an instant cut.
    source = clock_screens.render_screen(clock_screens.SCREEN_SEASON, _RTC_VALUE[:7])
    middle = display.shown[ct.TRANSITION_STEPS // 2]
    assert not same_frame(middle, source)
    assert not same_frame(middle, engine.screen_frame)


def test_wait_transition_scrolls_the_wait_screen_into_itself(paced_engine: tuple) -> None:
    """The GPS-wait animation never blanks: it scrolls WAIT_ON into a fresh copy.

    The sequence always lands WAIT_ON before looping this animation, so the
    scroll runs from the wait screen into itself rather than from a dark frame.
    Frames must also keep *moving* — a static repeat would satisfy "never dark"
    while showing the user a frozen display.
    """
    engine, display, _clock = paced_engine
    _land(engine, clock_screens.WAIT_ON)
    display.shown.clear()

    asyncio.run(clock_cycle.play_wait_transition(engine))

    assert engine.current_screen == clock_screens.WAIT_ON
    assert len(display.shown) > 1
    assert all(any(frame.data) for frame in display.shown)
    assert any(not same_frame(earlier, later) for earlier, later in pairwise(display.shown))


def test_hold_screen_waits_for_its_duration_and_periodically_refreshes(
    paced_engine: tuple,
) -> None:
    engine, display, clock = paced_engine
    _land(engine, clock_screens.SCREEN_MAIN)
    hold_ms = clock_screens.screen_spec(clock_screens.SCREEN_MAIN).hold_ms
    started = clock.ticks

    asyncio.run(clock_cycle.hold_screen(engine))

    assert clock.ticks - started == hold_ms
    assert len(display.shown) == 1 + hold_ms // clock_cycle.REASSERT_MS


def test_hold_screen_breaks_out_early_when_the_stop_predicate_fires(
    paced_engine: tuple,
) -> None:
    """The GPS-wait hold must end the moment a fix arrives, not 3 minutes later."""
    engine, _display, clock = paced_engine
    _land(engine, clock_screens.WAIT_ON)
    started = clock.ticks

    def _stop() -> bool:
        return clock.ticks - started >= 2 * clock_cycle.POLL_SLEEP_MS

    asyncio.run(clock_cycle.hold_screen(engine, stop=_stop))

    assert clock.ticks - started == 2 * clock_cycle.POLL_SLEEP_MS


def test_hold_screen_returns_immediately_when_the_fix_is_already_in(
    paced_engine: tuple,
) -> None:
    """A fix that landed during the transition must not cost one more hold tick."""
    engine, display, clock = paced_engine
    _land(engine, clock_screens.WAIT_ON)
    display.shown.clear()
    started = clock.ticks

    asyncio.run(clock_cycle.hold_screen(engine, stop=lambda: True))

    assert clock.ticks == started
    assert display.shown == []


def test_held_uptime_screen_advances_its_marquee_every_scroll_step(
    paced_engine: tuple,
) -> None:
    """Holding the uptime screen must keep the two marquee rows moving.

    The engine feeds `ticks_ms()` in as the scroll phase and the screen keys on
    whole pixels of travel, so a hold has to re-render roughly every
    `SCROLL_MS_PER_PX`. Nothing else covers that composition, and a key that
    dropped the scroll term would freeze the marquee while every isolated
    screen and engine test still passed.
    """
    engine, display, clock = paced_engine
    engine._sync = SimpleNamespace(boot_time=(2026, 6, 23, 1, 12, 0, 0))
    _land(engine, clock_screens.SCREEN_UPTIME)
    display.shown.clear()
    started = clock.ticks

    asyncio.run(clock_cycle.hold_screen(engine))

    held_ms = clock.ticks - started
    assert held_ms == clock_screens.screen_spec(clock_screens.SCREEN_UPTIME).hold_ms
    # One redraw per pixel of marquee travel, give or take the final partial step.
    expected_redraws = held_ms // clock_screens.SCROLL_MS_PER_PX
    assert abs(len(display.shown) - expected_redraws) <= 1
    assert any(not same_frame(earlier, later) for earlier, later in pairwise(display.shown))


def test_frame_rate_test_runs_for_its_hold_and_reports_rising_frame_counts(
    paced_engine: tuple,
) -> None:
    engine, _display, clock = paced_engine
    samples: list = []
    engine.show_frame_rate = lambda count, elapsed, _now: samples.append((count, elapsed))

    asyncio.run(clock_cycle.run_frame_rate_test(engine))

    hold_ms = clock_screens.screen_spec(clock_screens.SCREEN_FRAME_RATE).hold_ms
    assert samples == list(enumerate(range(0, hold_ms, clock_cycle.POLL_SLEEP_MS), 1))
    assert hold_ms <= clock.ticks < hold_ms + clock_cycle.POLL_SLEEP_MS


def test_startup_handoff_shows_the_brand_then_dissolves_to_the_target(
    paced_engine: tuple,
) -> None:
    engine, _display, clock = paced_engine
    visited: list = []
    original = engine.begin_transition

    def _record(target: int, *, effect: int | None = None, direction: int | None = None) -> None:
        visited.append((target, effect, direction, clock.ticks))
        original(target, effect=effect, direction=direction)

    engine.begin_transition = _record

    asyncio.run(clock_cycle.play_startup_handoff(engine, clock_screens.SCREEN_MAIN))

    assert [visit[:3] for visit in visited] == [
        (clock_screens.SCREEN_BRAND, ct.TRANSITION_SCROLL, ct.DIRECTION_RIGHT),
        (clock_screens.SCREEN_MAIN, ct.TRANSITION_DISSOLVE, ct.DIRECTION_LEFT),
    ]
    assert visited[1][3] == (
        (ct.TRANSITION_STEPS - 1) * clock_cycle.FRAME_BUDGET_MS
        + clock_screens.screen_spec(clock_screens.SCREEN_BRAND).hold_ms
    )
    assert engine.current_screen == clock_screens.SCREEN_MAIN


@pytest.mark.parametrize(
    "render_ms,expected_sleep",
    [
        (0, clock_cycle.FRAME_BUDGET_MS),
        (10, clock_cycle.FRAME_BUDGET_MS - 10),
        (clock_cycle.FRAME_BUDGET_MS, clock_cycle.MIN_FRAME_YIELD_MS),
        (clock_cycle.FRAME_BUDGET_MS * 3, clock_cycle.MIN_FRAME_YIELD_MS),
    ],
    ids=["idle", "within-budget", "at-budget", "over-budget"],
)
@pytest.mark.parametrize("start", [0, (1 << 30) - 5], ids=["normal-ticks", "wrapped-ticks"])
def test_transition_pacing_accounts_for_render_cost_and_always_yields(
    monkeypatch: pytest.MonkeyPatch, render_ms: int, expected_sleep: int, start: int
) -> None:
    clock = ManualTime()
    clock.ticks = start
    tick_period = 1 << 30
    wrapping_clock = SimpleNamespace(
        ticks_ms=lambda: clock.ticks % tick_period,
        ticks_diff=lambda new, old: (new - old + tick_period // 2) % tick_period - tick_period // 2,
    )
    slept: list = []
    frame_starts: list = []

    def _render(_now: int) -> bool:
        frame_starts.append(clock.ticks - start)
        clock.advance(render_ms)
        return len(frame_starts) == 3

    async def _record(ms: int) -> None:
        slept.append(ms)
        clock.advance(ms)
        await asyncio.sleep(0)

    monkeypatch.setattr(asyncio, "sleep_ms", _record)
    engine = SimpleNamespace(
        clock=wrapping_clock,
        begin_transition=lambda *_args, **_kwargs: None,
        advance_transition=_render,
    )

    asyncio.run(clock_cycle.play_transition(engine, clock_screens.SCREEN_MAIN))

    assert slept == [expected_sleep, expected_sleep]
    assert frame_starts == [0, render_ms + expected_sleep, 2 * (render_ms + expected_sleep)]


# --------------------------------------------------------------------------
# DisplayEngine: geometry, transition endpoints, frame cache, healing.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("geometry", [(32, 16), (64, 16)])
def test_engine_renders_at_the_displays_declared_geometry(geometry: tuple) -> None:
    display = FakeDisplay(*geometry)

    engine = clock_cycle.DisplayEngine(
        display, machine.RTC(_RTC_VALUE), clock=ManualTime(), rng=FakeRandom([0])
    )
    _land(engine, clock_screens.SCREEN_MAIN)

    assert same_frame(
        display.shown[-1],
        clock_screens.render_screen(clock_screens.SCREEN_MAIN, _RTC_VALUE[:7], *geometry),
    )


@pytest.mark.parametrize("screen", [clock_screens.SCREEN_MAIN, clock_screens.WAIT_ON])
def test_animated_transition_lands_after_the_screens_step_budget(
    engine: clock_cycle.DisplayEngine, screen: int
) -> None:
    steps = ct.TRANSITION_STEPS
    engine.begin_transition(screen, effect=ct.TRANSITION_WIPE)

    landings = [engine.advance_transition(step) for step in range(steps)]

    assert landings[:-1] == [False] * (steps - 1)
    assert landings[-1] is True
    assert engine.current_screen == screen
    assert same_frame(engine._display.shown[-1], engine.screen_frame)


def test_first_transition_starts_from_the_blank_wait_endpoint(
    engine: clock_cycle.DisplayEngine,
) -> None:
    """With nothing on screen yet, the source is the dark wait frame, not a crash."""
    engine.begin_transition(clock_screens.SCREEN_MAIN, effect=ct.TRANSITION_WIPE)

    source = engine.transition.source_frame
    blank = clock_screens.render_screen(clock_screens.WAIT_OFF, None)
    assert same_frame(source, blank)


def test_transition_reuses_the_frame_already_on_screen_as_its_source(
    engine: clock_cycle.DisplayEngine,
) -> None:
    """The source endpoint is the exact frame being displayed, not a re-render."""
    _land(engine, clock_screens.SCREEN_MAIN)
    landed_frame = engine.screen_frame

    engine.begin_transition(clock_screens.SCREEN_SEASON, effect=ct.TRANSITION_WIPE)

    assert engine.transition.source_frame is landed_frame


def test_frames_are_cached_per_screen_until_the_content_key_changes(
    engine: clock_cycle.DisplayEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    render = Mock(wraps=clock_screens.render_screen)
    monkeypatch.setattr(clock_screens, "render_screen", render)
    for screen in (
        clock_screens.SCREEN_MAIN,
        clock_screens.SCREEN_SEASON,
        clock_screens.SCREEN_MAIN,
    ):
        _land(engine, screen)
    engine.reassert(clock_cycle.REASSERT_MS)

    assert [call.args[0] for call in render.call_args_list] == [
        clock_screens.WAIT_OFF,
        clock_screens.SCREEN_MAIN,
        clock_screens.SCREEN_SEASON,
    ]
    render.reset_mock()
    engine._rtc.value = (2026, 6, 23, 1, 12, 31, 0, 0)
    engine.reassert(clock_cycle.REASSERT_MS + 1)

    render.assert_called_once_with(clock_screens.SCREEN_MAIN, engine._rtc.value[:7], 32, 16)


def test_reassert_redraws_when_the_visible_content_changes(
    engine: clock_cycle.DisplayEngine,
) -> None:
    _land(engine, clock_screens.SCREEN_MAIN)
    shown_before = len(engine._display.shown)

    engine._rtc.value = (2026, 6, 23, 1, 12, 30, 1, 0)  # colon blink, one second on
    engine.reassert(10)

    assert len(engine._display.shown) == shown_before + 1
    assert same_frame(
        engine._display.shown[-1],
        clock_screens.render_screen(clock_screens.SCREEN_MAIN, engine._rtc.value[:7]),
    )


def test_reassert_stays_quiet_until_the_heal_interval_then_rewrites_the_panel(
    engine: clock_cycle.DisplayEngine,
) -> None:
    """Unchanged content is rewritten only periodically, so a garbled panel recovers."""
    _land(engine, clock_screens.SCREEN_MAIN)
    engine.reassert(0)
    shown_before = len(engine._display.shown)

    engine.reassert(10)
    engine.reassert(clock_cycle.REASSERT_MS - 1)
    assert len(engine._display.shown) == shown_before

    engine.reassert(clock_cycle.REASSERT_MS)
    assert len(engine._display.shown) == shown_before + 1


def test_every_screen_that_lands_also_stamps_the_heal_deadline(
    engine: clock_cycle.DisplayEngine,
) -> None:
    """`reassert` compares against `last_reassert_ms` without a null guard.

    That is only safe because landing a transition and rendering a diagnostic
    both stamp it, so the two ways `current_screen` becomes non-None are pinned
    here together.
    """
    assert (engine.current_screen, engine.last_reassert_ms) == (None, None)

    _land(engine, clock_screens.SCREEN_MAIN)
    assert engine.last_reassert_ms is not None

    fresh = clock_cycle.DisplayEngine(
        FakeDisplay(), machine.RTC(_RTC_VALUE), clock=ManualTime(), rng=FakeRandom([0])
    )
    fresh.show_frame_rate(1, 100, 7)
    assert (fresh.current_screen, fresh.last_reassert_ms) == (clock_screens.SCREEN_FRAME_RATE, 7)


def test_idle_engine_does_not_write_the_display(
    engine: clock_cycle.DisplayEngine,
) -> None:
    engine.reassert(0)

    assert engine.advance_transition(0) is True
    assert engine._display.shown == []
    assert engine.current_screen is None


def test_landing_refreshes_a_target_whose_content_moved_mid_transition(
    engine: clock_cycle.DisplayEngine,
) -> None:
    """Endpoints are snapshotted, so a clock that ticks in flight needs one redraw."""
    engine.begin_transition(clock_screens.SCREEN_MAIN, effect=ct.TRANSITION_WIPE)
    target_snapshot = engine.transition.target_frame.copy()
    for step in range(ct.TRANSITION_STEPS - 1):
        engine.advance_transition(step)

    engine._rtc.value = (2026, 6, 23, 1, 12, 31, 0, 0)  # minute rolls over in flight
    shown_before = len(engine._display.shown)
    engine.advance_transition(ct.TRANSITION_STEPS)

    # One frame for the final transition step, one for the refreshed target.
    assert len(engine._display.shown) == shown_before + 2
    assert same_frame(engine._display.shown[-2], target_snapshot)
    assert same_frame(
        engine._display.shown[-1],
        clock_screens.render_screen(clock_screens.SCREEN_MAIN, engine._rtc.value[:7]),
    )
    assert engine.shown_key == clock_screens.screen_key(
        clock_screens.SCREEN_MAIN, engine._rtc.value[:7]
    )


def test_landing_does_not_redraw_when_the_target_content_is_unchanged(
    engine: clock_cycle.DisplayEngine,
) -> None:
    engine.begin_transition(clock_screens.SCREEN_MAIN, effect=ct.TRANSITION_WIPE)
    for step in range(ct.TRANSITION_STEPS - 1):
        engine.advance_transition(step)
    shown_before = len(engine._display.shown)

    engine.advance_transition(ct.TRANSITION_STEPS)

    assert len(engine._display.shown) == shown_before + 1


@pytest.mark.parametrize(
    "frame_count,elapsed_ms,expected",
    [
        (18, 1_000, 180),  # 18 fps -> 18.0
        (9, 500, 180),
        (0, 1_000, 0),
        (5, 0, 0),  # no elapsed time yet: report zero rather than divide by zero
        (5, -1, 0),
    ],
)
def test_frame_rate_reports_tenths_and_cancels_any_transition(
    engine: clock_cycle.DisplayEngine, frame_count: int, elapsed_ms: int, expected: int
) -> None:
    engine.begin_transition(clock_screens.SCREEN_MAIN, effect=ct.TRANSITION_WIPE)

    engine.show_frame_rate(frame_count, elapsed_ms, 0)

    assert engine.current_screen == clock_screens.SCREEN_FRAME_RATE
    assert engine.transition is None
    assert same_frame(
        engine._display.shown[-1],
        clock_screens.render_screen(
            clock_screens.SCREEN_FRAME_RATE, (frame_count, elapsed_ms, expected)
        ),
    )


def test_uptime_screen_receives_the_latched_boot_time(engine_with_sync: tuple) -> None:
    engine, sync = engine_with_sync
    sync.boot_time = (2026, 6, 23, 1, 12, 0, 0)
    engine.clock.advance(4_000)

    boot, now, scroll_ms = engine._parts_for_screen(clock_screens.SCREEN_UPTIME)

    assert boot == sync.boot_time
    assert now == engine._rtc.value[:7]
    assert scroll_ms == 4_000


def test_uptime_screen_tolerates_a_missing_synchronizer(
    engine: clock_cycle.DisplayEngine,
) -> None:
    boot, _now, _scroll_ms = engine._parts_for_screen(clock_screens.SCREEN_UPTIME)

    assert boot is None


def test_wait_screens_render_without_rtc_parts(engine: clock_cycle.DisplayEngine) -> None:
    assert engine._parts_for_screen(clock_screens.WAIT_ON) is None


def test_transition_without_a_forced_effect_draws_both_from_the_tables(
    engine: clock_cycle.DisplayEngine,
) -> None:
    engine.rng = FakeRandom([1, 3])  # -> TRANSITION_DISSOLVE, then DIRECTIONS[3]

    engine.begin_transition(clock_screens.SCREEN_MAIN)

    assert engine.transition.effect == ct.TRANSITION_DISSOLVE
    assert engine.transition.direction == ct.DIRECTIONS[3]


def _land(engine: clock_cycle.DisplayEngine, screen: int) -> None:
    """Put ``screen`` on the display immediately."""
    engine.begin_transition(screen, effect=ct.TRANSITION_INSTANT)
    engine.advance_transition(0)


@pytest.fixture
def engine() -> clock_cycle.DisplayEngine:
    """Return an engine over fake hardware with a manually advanced clock."""
    return clock_cycle.DisplayEngine(
        FakeDisplay(),
        machine.RTC(_RTC_VALUE),
        clock=ManualTime(),
        rng=FakeRandom([0]),
    )


@pytest.fixture
def engine_with_sync() -> tuple:
    """Return an ``(engine, sync)`` pair sharing a synchronizer stub."""
    rtc = machine.RTC(_RTC_VALUE)
    sync = clock_sync.ClockSynchronizer(rtc)
    engine = clock_cycle.DisplayEngine(
        FakeDisplay(), rtc, clock=ManualTime(), rng=FakeRandom([0]), sync=sync
    )
    return engine, sync


@pytest.fixture
def paced_engine(monkeypatch: pytest.MonkeyPatch, engine: clock_cycle.DisplayEngine) -> tuple:
    """Return ``(engine, display, clock)`` with sleeping wired to the clock.

    ``asyncio.sleep_ms`` advances this clock by the requested interval and then
    yields immediately, so the coroutines' wall-clock deadlines are reached by
    the act of sleeping rather than by real elapsed time. Without it a 3-minute
    screen hold would take 3 real minutes.
    """
    clock = engine.clock
    real_sleep = asyncio.sleep_ms

    async def _advancing_sleep(ms: int) -> None:
        clock.advance(max(1, ms))
        await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep_ms", _advancing_sleep)
    return engine, engine._display, clock
