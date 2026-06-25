"""Display engine and step coroutines for clock screens and transitions."""

import asyncio
import random
import time

import clock_screens
import clock_transitions

POLL_SLEEP_MS = 50
REASSERT_MS = 5_000
WAIT_TRANSITION_STEPS = max(1, clock_screens.WAIT_ROTATE_MS // POLL_SLEEP_MS)


async def play_transition(engine: object, target: int, clock: object) -> None:
    """Animate the transition into ``target``, one frame per poll interval."""
    engine.begin_transition(target)
    while not engine.advance_transition(clock.ticks_ms()):
        await asyncio.sleep_ms(POLL_SLEEP_MS)


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


class TransitionRun:
    """State for one in-progress display transition."""

    def __init__(
        self,
        effect: int,
        target_screen: int,
        source_frame: object,
        target_frame: object,
        target_key: tuple,
        steps: int,
    ) -> None:
        """Store transition endpoints and the next frame step."""
        self.effect = effect
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

    def begin_transition(self, target_screen: int) -> None:
        """Start a transition from the current screen into ``target_screen``."""
        source = self.current_screen
        if source is None:
            source = clock_screens.WAIT_OFF
        steps = (
            WAIT_TRANSITION_STEPS
            if clock_screens.is_wait(target_screen)
            else clock_transitions.TRANSITION_STEPS
        )
        self._start_transition(source, target_screen, steps)

    def advance_transition(self, now: int) -> bool:
        """Render one transition frame; return whether the transition has landed."""
        self._advance_transition(now)
        return self.transition is None

    def reassert(self, now: int) -> None:
        """Refresh live content changes or periodically heal the current screen."""
        self._show_current_or_reassert(now)

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

    def _start_transition(self, source_screen: int, target_screen: int, steps: int) -> None:
        """Snapshot source and target frames for a transition run."""
        effect = clock_transitions.choose_transition(self._rng)
        source_parts = self._parts_for_screen(source_screen)
        target_parts = self._parts_for_screen(target_screen)
        source_frame = clock_transitions.as_packed_frame(
            self._frame_and_key(source_screen, source_parts)[0],
        )
        target_frame, target_key = self._frame_and_key(target_screen, target_parts)
        self.transition = TransitionRun(
            effect,
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
