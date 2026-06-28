"""Display engine and step coroutines for clock screens and transitions."""

import asyncio
import random
import time

import clock_screens
import clock_transitions

POLL_SLEEP_MS = 10
FRAME_RATE_TEST_SLEEP_MS = POLL_SLEEP_MS
REASSERT_MS = 5_000

# Adaptive animation frame pacing. Transition frames are paced to a wall-clock
# budget instead of a fixed inter-frame sleep: each frame sleeps only the time
# left in its budget after rendering, so frames land at an even cadence (less
# visible jank) and the loop never re-renders faster than the eye resolves
# (fewer SPI bursts → less switching power). When a render overruns its budget
# the rate adapts downward — the next frame starts as soon as the scheduler
# yields back — so animations stay smooth even with the core clock dialed down.
TARGET_FPS = 18
FRAME_BUDGET_MS = 1_000 // TARGET_FPS
# Floor on the per-frame sleep so the cooperative GPS pump is always scheduled,
# even when a render eats the whole budget.
MIN_FRAME_YIELD_MS = 2
WAIT_TRANSITION_STEPS = min(
    clock_transitions.TRANSITION_STEPS,
    max(1, clock_screens.WAIT_ROTATE_MS // POLL_SLEEP_MS),
)


async def play_transition(
    engine: object,
    target: int,
    clock: object,
    *,
    effect: int | None = None,
    direction: int | None = None,
) -> None:
    """Animate the transition into ``target``, one frame per adaptive budget."""
    engine.begin_transition(target, effect=effect, direction=direction)
    while True:
        frame_start = clock.ticks_ms()
        if engine.advance_transition(frame_start):
            return
        await _pace_frame(clock, frame_start)


async def _pace_frame(clock: object, frame_start: int) -> None:
    """Sleep the remainder of this frame's budget, never below the yield floor.

    Pacing from ``frame_start`` (taken before the render) keeps frame spacing
    even regardless of how long the render took, and collapses to
    ``MIN_FRAME_YIELD_MS`` when a render overruns so the rate degrades
    gracefully instead of accumulating lag.
    """
    remaining = FRAME_BUDGET_MS - clock.ticks_diff(clock.ticks_ms(), frame_start)
    await asyncio.sleep_ms(max(MIN_FRAME_YIELD_MS, remaining))


async def play_dissolve_transition(engine: object, target: int, clock: object) -> None:
    """Dissolve the current display state into ``target``."""
    await play_transition(
        engine,
        target,
        clock,
        effect=clock_transitions.TRANSITION_DISSOLVE,
        direction=clock_transitions.DIRECTION_LEFT,
    )


async def play_wait_transition(engine: object, clock: object) -> None:
    """Scroll the GPS-wait screen back into itself for the looping wait animation.

    The wait screen scrolls into a fresh copy of itself rather than blinking to a
    blank endpoint, so ``GPS WAIT`` stays continuously on screen — an unsynced
    display that animates in place instead of going dark every other second.
    """
    await play_transition(
        engine,
        clock_screens.WAIT_ON,
        clock,
        effect=clock_transitions.TRANSITION_SCROLL,
        direction=clock_transitions.DIRECTION_RIGHT,
    )


async def hold_screen(engine: object, clock: object, *, stop: object = None) -> None:
    """Hold the landed screen for its spec'd time, healing live content each frame.

    Args:
        engine: The :class:`DisplayEngine` whose ``current_screen`` is held.
        clock: ``time``-like source providing ``ticks_ms``/``ticks_diff``.
        stop: Optional predicate; when it returns true the hold ends early. Used
            by the GPS-wait blink to break out the moment a fix arrives.
    """
    deadline = clock.ticks_ms()
    hold_ms = clock_screens.screen_spec(engine.current_screen).hold_ms
    while clock.ticks_diff(clock.ticks_ms(), deadline) < hold_ms:
        if stop is not None and stop():
            return
        await asyncio.sleep_ms(POLL_SLEEP_MS)
        engine.reassert(clock.ticks_ms())


async def run_frame_rate_test(engine: object, clock: object) -> None:
    """Render the startup display frame-rate diagnostic for its screen hold."""
    start = clock.ticks_ms()
    frame_count = 0
    hold_ms = clock_screens.screen_spec(clock_screens.SCREEN_FRAME_RATE).hold_ms
    while True:
        now = clock.ticks_ms()
        elapsed_ms = clock.ticks_diff(now, start)
        if elapsed_ms >= hold_ms:
            return
        frame_count += 1
        engine.show_frame_rate(frame_count, elapsed_ms, now)
        await asyncio.sleep_ms(FRAME_RATE_TEST_SLEEP_MS)


async def play_startup_handoff(engine: object, target: int, clock: object) -> None:
    """Scroll the diagnostic away, show the brand, then dissolve into ``target``."""
    await play_transition(
        engine,
        clock_screens.SCREEN_BRAND,
        clock,
        effect=clock_transitions.TRANSITION_SCROLL,
        direction=clock_transitions.DIRECTION_RIGHT,
    )
    await hold_screen(engine, clock)
    await play_dissolve_transition(engine, target, clock)


class TransitionRun:
    """State for one in-progress display transition."""

    def __init__(
        self,
        effect: int,
        direction: int,
        target_screen: int,
        source_frame: object,
        target_frame: object,
        target_key: tuple,
        steps: int,
    ) -> None:
        """Store transition endpoints and the next frame step."""
        self.effect = effect
        self.direction = direction
        self.target_screen = target_screen
        self.source_frame = source_frame
        self.target_frame = target_frame
        self.target_key = target_key
        self.step = 1
        self.steps = 1 if effect == clock_transitions.TRANSITION_INSTANT else steps


class DisplayEngine:
    """Render wait screens, regular screens, interstitials, and transitions.

    Exposes synchronous step primitives (`begin_transition`, `advance_transition`,
    `reassert`) that the module-level coroutines drive in `await`-sleep loops; the
    screen *order* lives in the caller, not in this engine.
    """

    def __init__(
        self,
        display: object,
        rtc: object,
        *,
        clock: object | None = None,
        rng: object | None = None,
    ) -> None:
        """Bind the engine to a display, RTC, clock source, and RNG."""
        self._display = display
        self._rtc = rtc
        self._clock = time if clock is None else clock
        self._rng = random if rng is None else rng
        self._width_pixels = getattr(display, "width_pixels", clock_screens.WIDTH_PIXELS)
        self._height_pixels = getattr(display, "height_pixels", clock_screens.HEIGHT_PIXELS)
        self._frame_cache = {}
        self.current_screen = None
        self.last_reassert_ms = None
        self.shown_key = None
        self.screen_frame = None
        self.transition = None

    def begin_transition(
        self,
        target_screen: int,
        *,
        effect: int | None = None,
        direction: int | None = None,
    ) -> None:
        """Start a transition from the current screen into ``target_screen``."""
        source = self.current_screen
        if source is None:
            source = clock_screens.WAIT_OFF
        steps = (
            WAIT_TRANSITION_STEPS
            if clock_screens.is_wait(target_screen)
            else clock_transitions.TRANSITION_STEPS
        )
        self._start_transition(source, target_screen, steps, effect=effect, direction=direction)

    def advance_transition(self, now: int) -> bool:
        """Render one transition frame; return whether the transition has landed."""
        self._advance_transition(now)
        return self.transition is None

    def reassert(self, now: int) -> None:
        """Refresh live content changes or periodically heal the current screen."""
        self._show_current_or_reassert(now)

    def show_frame_rate(self, frame_count: int, elapsed_ms: int, now: int) -> None:
        """Render one diagnostic sample while measuring display throughput."""
        parts = (frame_count, elapsed_ms, _frame_rate_x10(frame_count, elapsed_ms))
        frame, key = self._frame_and_key(clock_screens.SCREEN_FRAME_RATE, parts)
        self.current_screen = clock_screens.SCREEN_FRAME_RATE
        self.transition = None
        self._show_frame(frame, key, now)

    def _parts(self) -> tuple:
        """Return the current RTC parts snapshot."""
        return clock_screens.rtc_parts(self._rtc)

    def _parts_for_screen(self, screen: int) -> tuple | None:
        """Return RTC parts only for screens whose content depends on the RTC."""
        if clock_screens.is_wait(screen):
            return None
        return self._parts()

    def _frame_and_key(self, screen: int, parts: tuple | None) -> tuple:
        """Return a cached frame and its visible-content key."""
        key = clock_screens.screen_key(screen, parts)
        cached = self._frame_cache.get(screen)
        if cached is not None and cached[0] == key:
            return cached[1], key
        frame = clock_screens.render_screen(
            screen,
            parts,
            self._width_pixels,
            self._height_pixels,
        )
        self._frame_cache[screen] = (key, frame)
        return frame, key

    def _show_frame(self, frame: object, key: tuple, now: int) -> None:
        """Render ``frame`` and store the visible-content state."""
        self._display.show(frame)
        self.screen_frame = frame
        self.shown_key = key
        self.last_reassert_ms = now

    def _start_transition(
        self,
        source_screen: int,
        target_screen: int,
        steps: int,
        *,
        effect: int | None = None,
        direction: int | None = None,
    ) -> None:
        """Snapshot source and target frames for a transition run."""
        random_effect = effect is None
        if effect is None:
            effect = clock_transitions.choose_transition(self._rng)
        if direction is None:
            direction = _transition_direction(effect, random_effect=random_effect, rng=self._rng)
        source_parts = self._parts_for_screen(source_screen)
        target_parts = self._parts_for_screen(target_screen)
        if source_screen == self.current_screen and self.screen_frame is not None:
            source_frame = clock_transitions.as_packed_frame(self.screen_frame)
        else:
            source_frame = clock_transitions.as_packed_frame(
                self._frame_and_key(source_screen, source_parts)[0],
            )
        target_frame, target_key = self._frame_and_key(target_screen, target_parts)
        self.transition = TransitionRun(
            effect,
            direction,
            target_screen,
            source_frame,
            clock_transitions.as_packed_frame(target_frame),
            target_key,
            steps,
        )

    def _advance_transition(self, now: int) -> None:
        """Render at most one active transition frame."""
        transition = self.transition
        if transition is None:
            return
        frame = clock_transitions.frame_transition_frame(
            transition.effect,
            transition.source_frame,
            transition.target_frame,
            step=transition.step,
            steps=transition.steps,
            direction=transition.direction,
        )
        self._display.show(frame)
        self.last_reassert_ms = now
        if transition.step >= transition.steps:
            self._land_transition(transition, now)
            return
        transition.step += 1

    def _land_transition(self, transition: object, now: int) -> None:
        """Commit a completed transition and refresh changed target content."""
        target = transition.target_screen
        self.current_screen = target
        self.screen_frame = transition.target_frame
        self.shown_key = transition.target_key
        self.transition = None
        self._refresh_landed_target(now)

    def _refresh_landed_target(self, now: int) -> None:
        """Refresh the target once if its RTC-backed content changed in flight."""
        parts = self._parts_for_screen(self.current_screen)
        key = clock_screens.screen_key(self.current_screen, parts)
        if key == self.shown_key:
            return
        frame, key = self._frame_and_key(self.current_screen, parts)
        self._show_frame(frame, key, now)

    def _show_current_or_reassert(self, now: int) -> None:
        """Refresh live content changes or periodically heal display state."""
        if self.current_screen is None:
            return
        parts = self._parts_for_screen(self.current_screen)
        key = clock_screens.screen_key(self.current_screen, parts)
        if self.shown_key != key:
            frame, key = self._frame_and_key(self.current_screen, parts)
            self._show_frame(frame, key, now)
            return
        if self.last_reassert_ms is None:
            self.last_reassert_ms = now
            return
        if self._clock.ticks_diff(now, self.last_reassert_ms) >= REASSERT_MS:
            frame, _key = self._frame_and_key(self.current_screen, parts)
            self._show_frame(frame, key, now)


def _frame_rate_x10(frame_count: int, elapsed_ms: int) -> int:
    """Return frames per second as a fixed-point tenths value."""
    if elapsed_ms <= 0:
        return 0
    return frame_count * 10_000 // elapsed_ms


def _transition_direction(effect: int, *, random_effect: bool, rng: object) -> int:
    """Return the direction for either a random or forced transition effect."""
    if effect == clock_transitions.TRANSITION_INSTANT:
        return clock_transitions.DIRECTION_LEFT
    if random_effect:
        return clock_transitions.choose_direction(rng)
    if effect == clock_transitions.TRANSITION_SCROLL:
        return clock_transitions.DIRECTION_RIGHT
    return clock_transitions.DIRECTION_LEFT
