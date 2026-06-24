"""Display-cycle scheduler for clock screens and transitions."""

import random
import time

import clock_screens
import clock_transitions

POLL_SLEEP_MS = 50
REASSERT_MS = 5_000
WAIT_TRANSITION_STEPS = max(1, clock_screens.WAIT_ROTATE_MS // POLL_SLEEP_MS)


class DisplayCycle:
    """Advance wait screens, regular screens, interstitials, and transitions."""

    def __init__(
        self,
        display: object,
        rtc: object,
        intensity_limit: float,
        *,
        clock: object | None = None,
        rng: object | None = None,
    ) -> None:
        """Bind the cycle manager to a display, RTC, clock source, and RNG."""
        self._display = display
        self._rtc = rtc
        self._intensity_limit = intensity_limit
        self._clock = time if clock is None else clock
        self._rng = random if rng is None else rng
        self._frame_cache = {}
        self.current_screen = None
        self.previous_regular = clock_screens.SCREEN_MAIN
        self.screen_started_ms = None
        self.last_reassert_ms = None
        self.shown_key = None
        self.screen_frame = None
        self.transition = None

    def tick(self, synced: bool) -> None:
        """Render at most one display update for the current loop tick."""
        now = self._clock.ticks_ms()
        if not synced:
            self._tick_wait(now)
            return
        if self.current_screen is None or clock_screens.is_wait(self.current_screen):
            self.transition = None
            self._show_screen(clock_screens.SCREEN_MAIN, now)
            return
        if self.transition is not None:
            self._advance_transition(now)
            return
        if self._hold_expired(now):
            self._start_next_screen_transition()
            self._advance_transition(now)
            return
        self._show_current_or_reassert(now)

    def _tick_wait(self, now: int) -> None:
        """Animate the unsynced GPS wait display."""
        if self.transition is not None:
            self._advance_transition(now)
            return
        if self.current_screen not in clock_screens.WAIT_SCREENS:
            self.current_screen = clock_screens.WAIT_OFF
            self.shown_key = clock_screens.screen_key(clock_screens.WAIT_OFF, None)
            self.screen_started_ms = None
            self._start_wait_transition()
            self._advance_transition(now)
            return
        if self._hold_expired(now):
            self._start_wait_transition()
            self._advance_transition(now)
            return
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
        frame = clock_screens.render_screen(screen, parts)
        self._frame_cache[screen] = (key, frame)
        return frame, key

    def _show_screen(self, screen: int, now: int) -> None:
        """Render a stable screen and start its hold timer."""
        parts = self._parts_for_screen(screen)
        frame, key = self._frame_and_key(screen, parts)
        self._display.show(frame)
        self.current_screen = screen
        self.screen_frame = frame
        self.shown_key = key
        self.screen_started_ms = now
        self.last_reassert_ms = now

    def _hold_expired(self, now: int) -> bool:
        """Return whether the current screen's hold time has elapsed."""
        if self.current_screen is None or self.screen_started_ms is None:
            return True
        hold_ms = clock_screens.screen_spec(self.current_screen).hold_ms
        return self._clock.ticks_diff(now, self.screen_started_ms) >= hold_ms

    def _start_wait_transition(self) -> None:
        """Create transition state for the next GPS wait on/off flip."""
        source = self.current_screen
        if source not in clock_screens.WAIT_SCREENS:
            source = clock_screens.WAIT_OFF
        target = (
            clock_screens.WAIT_OFF if source == clock_screens.WAIT_ON else clock_screens.WAIT_ON
        )
        self._start_transition(source, target, WAIT_TRANSITION_STEPS)

    def _start_next_screen_transition(self) -> None:
        """Create transition state for the next synced screen hop."""
        current = self.current_screen
        if clock_screens.is_interstitial(current):
            target = clock_screens.choose_next_regular(self.previous_regular, self._rng)
        else:
            self.previous_regular = current
            target = clock_screens.choose_interstitial(self._rng)
        self._start_transition(current, target, clock_transitions.TRANSITION_STEPS)

    def _start_transition(self, source_screen: int, target_screen: int, steps: int) -> None:
        """Snapshot source and target frames for a transition run."""
        effect = clock_transitions.choose_transition(self._rng)
        source_parts = self._parts_for_screen(source_screen)
        target_parts = self._parts_for_screen(target_screen)
        source_frame = self._frame_and_key(source_screen, source_parts)[0]
        target_frame, target_key = self._frame_and_key(target_screen, target_parts)
        self.transition = {
            "effect": effect,
            "source_screen": source_screen,
            "target_screen": target_screen,
            "source_frame": source_frame,
            "target_frame": target_frame,
            "target_key": target_key,
            "step": 1,
            "steps": 1 if effect == clock_transitions.TRANSITION_INSTANT else steps,
        }

    def _advance_transition(self, now: int) -> None:
        """Render at most one active transition frame."""
        transition = self.transition
        frame = clock_transitions.frame_transition_frame(
            transition["effect"],
            transition["source_frame"],
            transition["target_frame"],
            step=transition["step"],
            steps=transition["steps"],
            intensity_limit=self._intensity_limit,
        )
        self._display.show(frame)
        self.last_reassert_ms = now
        if transition["step"] >= transition["steps"]:
            self._land_transition(transition, now)
            return
        transition["step"] += 1

    def _land_transition(self, transition: dict, now: int) -> None:
        """Commit a completed transition and refresh changed target content."""
        target = transition["target_screen"]
        self.current_screen = target
        self.screen_frame = transition["target_frame"]
        self.shown_key = transition["target_key"]
        self.screen_started_ms = now
        self.transition = None
        self._refresh_landed_target(now)

    def _refresh_landed_target(self, now: int) -> None:
        """Refresh the target once if its RTC-backed content changed in flight."""
        parts = self._parts_for_screen(self.current_screen)
        key = clock_screens.screen_key(self.current_screen, parts)
        if key == self.shown_key:
            return
        frame, key = self._frame_and_key(self.current_screen, parts)
        self._display.show(frame)
        self.screen_frame = frame
        self.shown_key = key
        self.last_reassert_ms = now

    def _show_current_or_reassert(self, now: int) -> None:
        """Refresh live content changes or periodically heal display state."""
        if self.current_screen is None:
            return
        parts = self._parts_for_screen(self.current_screen)
        key = clock_screens.screen_key(self.current_screen, parts)
        if self.shown_key != key:
            frame, key = self._frame_and_key(self.current_screen, parts)
            self._display.show(frame)
            self.screen_frame = frame
            self.shown_key = key
            self.last_reassert_ms = now
            return
        if self.last_reassert_ms is None:
            self.last_reassert_ms = now
            return
        if self._clock.ticks_diff(now, self.last_reassert_ms) >= REASSERT_MS:
            frame, _key = self._frame_and_key(self.current_screen, parts)
            self._display.show(frame)
            self.screen_frame = frame
            self.last_reassert_ms = now
