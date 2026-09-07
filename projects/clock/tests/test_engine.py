"""Host CPython tests for the DisplayEngine rendering mechanics.

The engine owns three jobs: caching rendered frames per screen, running a
transition between two snapshotted endpoints, and healing the display when
content changes or the panel drifts. Screen *order* lives in main.py and is
tested there.
"""

from __future__ import annotations

import pytest
from fake_clock import FakeDisplay, FakeRandom, FakeRTC, ManualTime, same_frame

import clock_cycle
import clock_screens
import clock_transitions as ct

_PARTS = (2026, 6, 23, 1, 12, 30, 0, 0)


def test_engine_starts_with_nothing_shown(engine: clock_cycle.DisplayEngine) -> None:
    assert engine.current_screen is None
    assert engine.screen_frame is None
    assert engine.transition is None


def test_engine_takes_geometry_from_the_display() -> None:
    display = FakeDisplay()
    display.width_pixels = 8
    display.height_pixels = 4

    engine = clock_cycle.DisplayEngine(display, FakeRTC(_PARTS), clock=ManualTime())
    engine.begin_transition(clock_screens.SCREEN_MAIN, effect=ct.TRANSITION_INSTANT)
    engine.advance_transition(0)

    assert (display.shown[-1].width, display.shown[-1].height) == (8, 4)


def test_engine_falls_back_to_the_default_geometry(engine: clock_cycle.DisplayEngine) -> None:
    """A display that does not declare its size gets the project's 32x16 default."""
    engine.begin_transition(clock_screens.SCREEN_MAIN, effect=ct.TRANSITION_INSTANT)
    engine.advance_transition(0)

    frame = engine._display.shown[-1]
    assert (frame.width, frame.height) == (
        clock_screens.WIDTH_PIXELS,
        clock_screens.HEIGHT_PIXELS,
    )


def test_instant_transition_lands_in_a_single_advance(
    engine: clock_cycle.DisplayEngine,
) -> None:
    engine.begin_transition(clock_screens.SCREEN_MAIN, effect=ct.TRANSITION_INSTANT)

    landed = engine.advance_transition(0)

    assert landed is True
    assert engine.transition is None
    assert engine.current_screen == clock_screens.SCREEN_MAIN


def test_animated_transition_reports_landing_only_on_the_final_step(
    engine: clock_cycle.DisplayEngine,
) -> None:
    engine.begin_transition(clock_screens.SCREEN_MAIN, effect=ct.TRANSITION_WIPE)

    landings = [engine.advance_transition(step) for step in range(ct.TRANSITION_STEPS)]

    assert landings[:-1] == [False] * (ct.TRANSITION_STEPS - 1)
    assert landings[-1] is True
    assert engine.current_screen == clock_screens.SCREEN_MAIN


def test_first_transition_starts_from_the_blank_wait_endpoint(
    engine: clock_cycle.DisplayEngine,
) -> None:
    """With nothing on screen yet, the source is the dark wait frame, not a crash."""
    engine.begin_transition(clock_screens.SCREEN_MAIN, effect=ct.TRANSITION_WIPE)

    source = engine.transition.source_frame
    blank = clock_screens.render_screen(clock_screens.WAIT_OFF, None)
    assert same_frame(source, blank)


def test_wait_transitions_use_the_shorter_step_budget(
    engine: clock_cycle.DisplayEngine,
) -> None:
    engine.begin_transition(clock_screens.WAIT_ON, effect=ct.TRANSITION_SCROLL)

    assert engine.transition.steps == clock_cycle.WAIT_TRANSITION_STEPS


def test_transition_reuses_the_frame_already_on_screen_as_its_source(
    engine: clock_cycle.DisplayEngine,
) -> None:
    """The source endpoint is the exact frame being displayed, not a re-render."""
    engine.begin_transition(clock_screens.SCREEN_MAIN, effect=ct.TRANSITION_INSTANT)
    engine.advance_transition(0)
    landed_frame = engine.screen_frame

    engine.begin_transition(clock_screens.SCREEN_SEASON, effect=ct.TRANSITION_WIPE)

    assert engine.transition.source_frame is landed_frame


def test_frames_are_cached_per_screen_until_the_content_key_changes(
    engine: clock_cycle.DisplayEngine,
) -> None:
    first, key = engine._frame_and_key(clock_screens.SCREEN_MAIN, engine._parts())
    again, again_key = engine._frame_and_key(clock_screens.SCREEN_MAIN, engine._parts())

    assert again is first  # cache hit: the same object, no re-render
    assert again_key == key

    engine._rtc.value = (2026, 6, 23, 1, 12, 31, 0, 0)
    changed, changed_key = engine._frame_and_key(clock_screens.SCREEN_MAIN, engine._parts())

    assert changed is not first
    assert changed_key != key


def test_reassert_redraws_when_the_visible_content_changes(
    engine: clock_cycle.DisplayEngine,
) -> None:
    engine.begin_transition(clock_screens.SCREEN_MAIN, effect=ct.TRANSITION_INSTANT)
    engine.advance_transition(0)
    shown_before = len(engine._display.shown)

    engine._rtc.value = (2026, 6, 23, 1, 12, 30, 1, 0)  # colon blink, one second on
    engine.reassert(10)

    assert len(engine._display.shown) == shown_before + 1


def test_reassert_is_quiet_while_the_content_is_unchanged(
    engine: clock_cycle.DisplayEngine,
) -> None:
    engine.begin_transition(clock_screens.SCREEN_MAIN, effect=ct.TRANSITION_INSTANT)
    engine.advance_transition(0)
    shown_before = len(engine._display.shown)

    engine.reassert(10)
    engine.reassert(20)

    assert len(engine._display.shown) == shown_before


def test_reassert_heals_the_panel_after_the_reassert_interval(
    engine: clock_cycle.DisplayEngine,
) -> None:
    """An unchanged screen is rewritten periodically so a garbled panel recovers."""
    engine.begin_transition(clock_screens.SCREEN_MAIN, effect=ct.TRANSITION_INSTANT)
    engine.advance_transition(0)
    engine.reassert(0)
    shown_before = len(engine._display.shown)

    engine.reassert(clock_cycle.REASSERT_MS - 1)
    assert len(engine._display.shown) == shown_before

    engine.reassert(clock_cycle.REASSERT_MS)
    assert len(engine._display.shown) == shown_before + 1


def test_reassert_does_nothing_before_the_first_screen(
    engine: clock_cycle.DisplayEngine,
) -> None:
    engine.reassert(0)

    assert engine._display.shown == []


def test_landing_refreshes_a_target_whose_content_moved_mid_transition(
    engine: clock_cycle.DisplayEngine,
) -> None:
    """Endpoints are snapshotted, so a clock that ticks in flight needs one redraw."""
    engine.begin_transition(clock_screens.SCREEN_MAIN, effect=ct.TRANSITION_WIPE)
    for step in range(ct.TRANSITION_STEPS - 1):
        engine.advance_transition(step)

    engine._rtc.value = (2026, 6, 23, 1, 12, 31, 0, 0)  # minute rolls over in flight
    shown_before = len(engine._display.shown)
    engine.advance_transition(ct.TRANSITION_STEPS)

    # One frame for the final transition step, one for the refreshed target.
    assert len(engine._display.shown) == shown_before + 2
    assert engine.shown_key == clock_screens.screen_key(clock_screens.SCREEN_MAIN, engine._parts())


def test_landing_does_not_redraw_when_the_target_content_is_unchanged(
    engine: clock_cycle.DisplayEngine,
) -> None:
    engine.begin_transition(clock_screens.SCREEN_MAIN, effect=ct.TRANSITION_WIPE)
    for step in range(ct.TRANSITION_STEPS - 1):
        engine.advance_transition(step)
    shown_before = len(engine._display.shown)

    engine.advance_transition(ct.TRANSITION_STEPS)

    assert len(engine._display.shown) == shown_before + 1


def test_show_frame_rate_renders_the_diagnostic_and_clears_any_transition(
    engine: clock_cycle.DisplayEngine,
) -> None:
    engine.begin_transition(clock_screens.SCREEN_MAIN, effect=ct.TRANSITION_WIPE)

    engine.show_frame_rate(9, 500, 0)

    assert engine.current_screen == clock_screens.SCREEN_FRAME_RATE
    assert engine.transition is None
    assert same_frame(
        engine._display.shown[-1],
        clock_screens.render_screen(clock_screens.SCREEN_FRAME_RATE, (9, 500, 180)),
    )


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
def test_frame_rate_is_reported_in_tenths(frame_count: int, elapsed_ms: int, expected: int) -> None:
    assert clock_cycle._frame_rate_x10(frame_count, elapsed_ms) == expected


def test_uptime_screen_receives_the_latched_boot_time(engine_with_sync: tuple) -> None:
    engine, sync = engine_with_sync
    sync.boot_time = (2026, 6, 23, 1, 12, 0, 0)
    engine._clock.advance(4_000)

    boot, now, scroll_ms = engine._parts_for_screen(clock_screens.SCREEN_UPTIME)

    assert boot == sync.boot_time
    assert now == engine._parts()
    assert scroll_ms == 4_000


def test_uptime_screen_tolerates_a_missing_synchronizer(
    engine: clock_cycle.DisplayEngine,
) -> None:
    boot, _now, _scroll_ms = engine._parts_for_screen(clock_screens.SCREEN_UPTIME)

    assert boot is None


def test_wait_screens_render_without_rtc_parts(engine: clock_cycle.DisplayEngine) -> None:
    assert engine._parts_for_screen(clock_screens.WAIT_ON) is None


@pytest.mark.parametrize(
    "effect,expected",
    [
        (ct.TRANSITION_INSTANT, ct.DIRECTION_LEFT),
        (ct.TRANSITION_SCROLL, ct.DIRECTION_RIGHT),
        (ct.TRANSITION_WIPE, ct.DIRECTION_LEFT),
    ],
)
def test_forced_effects_use_a_fixed_direction(effect: int, expected: int) -> None:
    direction = clock_cycle._transition_direction(effect, random_effect=False, rng=FakeRandom([0]))

    assert direction == expected


def test_randomly_chosen_effects_also_choose_a_random_direction() -> None:
    direction = clock_cycle._transition_direction(
        ct.TRANSITION_WIPE, random_effect=True, rng=FakeRandom([3])
    )

    assert direction == ct.DIRECTIONS[3]


def test_random_instant_effect_still_uses_the_fixed_direction() -> None:
    """INSTANT ignores direction entirely, so it must not consume a random value."""
    rng = FakeRandom([5])

    direction = clock_cycle._transition_direction(
        ct.TRANSITION_INSTANT, random_effect=True, rng=rng
    )

    assert direction == ct.DIRECTION_LEFT


def test_transition_without_a_forced_effect_draws_one_from_the_table(
    engine: clock_cycle.DisplayEngine,
) -> None:
    engine._rng = FakeRandom([1])  # -> TRANSITION_DISSOLVE

    engine.begin_transition(clock_screens.SCREEN_MAIN)

    assert engine.transition.effect == ct.TRANSITION_DISSOLVE


@pytest.fixture
def engine() -> clock_cycle.DisplayEngine:
    """Return an engine over fake hardware with a manually advanced clock."""
    return clock_cycle.DisplayEngine(
        FakeDisplay(),
        FakeRTC(_PARTS),
        clock=ManualTime(),
        rng=FakeRandom([0]),
    )


@pytest.fixture
def engine_with_sync() -> tuple:
    """Return an ``(engine, sync)`` pair sharing a synchronizer stub."""
    import clock_sync

    rtc = FakeRTC(_PARTS)
    sync = clock_sync.ClockSynchronizer(rtc)
    engine = clock_cycle.DisplayEngine(
        FakeDisplay(), rtc, clock=ManualTime(), rng=FakeRandom([0]), sync=sync
    )
    return engine, sync
