"""Host CPython tests for the clock project firmware."""

from __future__ import annotations

import json
from types import SimpleNamespace

import clock_hardware
import pytest

import clock_cycle
import clock_screens
import clock_sync
import clock_transitions
from pixel_frame import Frame, Text

_RMC_FIX = "$GPRMC,235958,A,3723.2475,N,12158.3416,W,0.0,0.0,230626,0.0,E*69"


class _StopLoop(BaseException):
    """Sentinel that escapes the run()/main() `except Exception` guards."""


class _CountdownTime:
    """time stub whose sleep_ms raises _StopLoop after `stop_after` calls."""

    def __init__(self, stop_after: int) -> None:
        """Initialise the countdown."""
        self.t = 0
        self._stop = stop_after
        self._sleeps = 0

    def ticks_ms(self) -> int:
        """Return a steadily increasing millisecond counter."""
        self.t += 1
        return self.t

    def ticks_diff(self, a: int, b: int) -> int:
        """Return the difference between two tick values."""
        return a - b

    def sleep_ms(self, _ms: int) -> None:
        """Count sleeps and raise the stop sentinel when the limit is reached."""
        self._sleeps += 1
        if self._sleeps >= self._stop:
            raise _StopLoop


class _ManualTime:
    """time stub whose tick counter can be moved by tests."""

    def __init__(self) -> None:
        """Initialise the tick counter."""
        self.ticks = 0

    def ticks_ms(self) -> int:
        """Advance and return the monotonic tick counter."""
        self.ticks += 1
        return self.ticks

    def ticks_diff(self, a: int, b: int) -> int:
        """Return the difference between two tick values."""
        return a - b


class _FakeDisplay:
    """Display stand-in recording abstract frame renders."""

    def __init__(self) -> None:
        """Initialise an empty call log."""
        self.shown: list[object] = []
        self.flips = 0

    def show(self, frame: object) -> None:
        """Record the requested frame."""
        self.shown.append(frame)

    def flip(self) -> None:
        """Record a display-orientation flip."""
        self.flips += 1


class _FakeGPS:
    """GPS stand-in returning scripted lines or raising scripted exceptions."""

    def __init__(self, lines: list) -> None:
        """Store scripted readline outcomes."""
        self._lines = list(lines)

    def readline(self) -> str | None:
        """Return the next scripted line, or None when exhausted."""
        if not self._lines:
            return None
        line = self._lines.pop(0)
        if isinstance(line, Exception):
            raise line
        return line


class _FakeRTC:
    """RTC stand-in supporting MicroPython's datetime getter/setter shape."""

    def __init__(self) -> None:
        """Start at a deterministic midnight."""
        self.value = (2026, 1, 1, 3, 0, 0, 0, 0)

    def datetime(self, value: tuple | None = None) -> tuple | None:
        """Get or set the stored RTC datetime tuple."""
        if value is None:
            return self.value
        self.value = tuple(value)
        return None


class _FakeRandom:
    """Deterministic getrandbits source for screen-cycle tests."""

    def __init__(self, values: list[int]) -> None:
        """Store the scripted random values."""
        self._values = list(values)

    def getrandbits(self, _bits: int) -> int:
        """Return the next scripted value."""
        return self._values.pop(0)


def test_emit_writes_one_json_line(capsys: pytest.CaptureFixture) -> None:
    """emit() writes exactly one compact JSON object per line."""
    clock_sync.emit({"fix": True, "day": "TUE"})
    out = capsys.readouterr().out.strip()
    assert json.loads(out) == {"fix": True, "day": "TUE"}


def test_run_waits_for_gps_before_first_fix(main_ns: object) -> None:
    """The matrix transitions onto GPS WAIT until a complete fix arrives."""
    main_ns.ns["time"] = _CountdownTime(stop_after=1)
    main_ns.ns["random"] = _FakeRandom([0])
    display = _FakeDisplay()

    with pytest.raises(_StopLoop):
        main_ns.ns["run"](_FakeGPS([None]), display, _FakeRTC())

    assert len(display.shown) == 1
    assert _same_frame(
        display.shown[0],
        clock_transitions.wipe_frame(
            clock_screens.render_screen(clock_screens.WAIT_OFF, None),
            clock_screens.render_screen(clock_screens.WAIT_ON, None),
            1,
            clock_cycle.WAIT_TRANSITION_STEPS,
        ),
    )
    assert "streaming" in main_ns.status.calls


def test_wait_screen_transitions_off_after_one_second() -> None:
    """The unsynced wait display flips between visible and blank endpoints."""
    clock = _ManualTime()
    display = _FakeDisplay()
    cycle = clock_cycle.DisplayCycle(
        display,
        _FakeRTC(),
        clock=clock,
        rng=_FakeRandom([3, 3]),
    )

    cycle.tick(synced=False)
    assert cycle.current_screen == clock_screens.WAIT_ON
    assert _same_frame(display.shown[-1], clock_screens.render_screen(clock_screens.WAIT_ON, None))

    phase_started = cycle.screen_started_ms
    clock.ticks = phase_started + clock_screens.WAIT_ROTATE_MS - 2
    cycle.tick(synced=False)
    assert len(display.shown) == 1

    clock.ticks = phase_started + clock_screens.WAIT_ROTATE_MS - 1
    cycle.tick(synced=False)
    assert cycle.current_screen == clock_screens.WAIT_OFF
    assert _same_frame(
        display.shown[-1],
        clock_screens.render_screen(clock_screens.WAIT_OFF, None),
    )


def test_wait_screen_holds_after_slow_transition_lands() -> None:
    """A long GPS wait transition starts its hold timer when it lands."""
    clock = _ManualTime()
    display = _FakeDisplay()
    cycle = clock_cycle.DisplayCycle(
        display,
        _FakeRTC(),
        clock=clock,
        rng=_FakeRandom([0]),
    )

    cycle.tick(synced=False)
    while cycle.transition is not None:
        cycle.tick(synced=False)
    landed = cycle.screen_started_ms
    shown_count = len(display.shown)
    clock.ticks = landed + clock_screens.WAIT_ROTATE_MS - 2
    cycle.tick(synced=False)

    assert cycle.current_screen == clock_screens.WAIT_ON
    assert cycle.transition is None
    assert len(display.shown) == shown_count


def test_run_syncs_rtc_and_displays_current_time_and_date(main_ns: object) -> None:
    """A valid RMC fix starts the synced display cycle on the main screen."""
    main_ns.ns["time"] = _CountdownTime(stop_after=1)
    emitted: list[dict] = []
    main_ns.ns["emit"] = lambda obj: emitted.append(dict(obj))
    display = _FakeDisplay()
    rtc = _FakeRTC()

    with pytest.raises(_StopLoop):
        main_ns.ns["run"](_FakeGPS([_RMC_FIX]), display, rtc)

    # California in June resolves to America/Los_Angeles -> PDT (UTC-7), so 23:59:58
    # UTC is 16:59:58 local, not the longitude-only 15:59:58 (UTC-8).
    assert rtc.value == (2026, 6, 23, 1, 16, 59, 58, 0)
    assert _same_frame(
        display.shown[-1],
        clock_screens.screen_frame(clock_screens.SCREEN_MAIN, rtc),
    )
    assert len(emitted) == 1
    assert emitted[0]["fix"] is True
    assert emitted[0]["lat"] == pytest.approx(37.387458, abs=1e-5)
    assert emitted[0]["lon"] == pytest.approx(-121.97236, abs=1e-5)
    assert emitted[0]["offset_h"] == -7
    assert emitted[0]["offset_min"] == -420
    assert emitted[0]["tz"] == "PDT"
    assert emitted[0]["local"] == "2026-06-23T16:59:58"
    assert emitted[0]["day"] == "TUE"
    assert emitted[0]["t"] == 1


def test_screen_specs_and_renderers_fit_the_matrix() -> None:
    """Every display-cycle screen renders to the fixed 32x16 packed surface."""
    rtc = _FakeRTC()
    rtc.value = (2026, 5, 31, 6, 23, 59, 58, 0)
    parts = clock_screens.rtc_parts(rtc)
    ids = [spec.id for spec in clock_screens.SCREEN_SPECS]

    assert len(ids) == len(set(ids))
    assert set(clock_screens.REGULAR_SCREENS) == {
        clock_screens.SCREEN_MAIN,
        clock_screens.SCREEN_CLOCK_MERIDIEM,
        clock_screens.SCREEN_TIME_SECONDS,
    }
    assert set(clock_screens.INTERSTITIAL_SCREENS) == {
        clock_screens.SCREEN_SEASON,
        clock_screens.SCREEN_FULL_DATE,
        clock_screens.SCREEN_UPTIME,
    }

    # The uptime screen takes a composite (boot, now, scroll_ms) parts tuple
    # rather than a bare RTC snapshot, so feed it boot == now for a clean frame.
    uptime_parts = (parts, parts, 0)
    for screen in clock_screens.REGULAR_SCREENS + clock_screens.INTERSTITIAL_SCREENS:
        screen_parts = uptime_parts if screen == clock_screens.SCREEN_UPTIME else parts
        frame = clock_screens.render_screen(screen, screen_parts)
        assert isinstance(frame, Frame)
        assert (frame.width, frame.height, frame.channels) == (32, 16, 1)
        assert any(frame.data)

    for screen in clock_screens.WAIT_SCREENS:
        frame = clock_screens.render_screen(screen, None)
        assert isinstance(frame, Frame)
        assert (frame.width, frame.height, frame.channels) == (32, 16, 1)


def test_season_name_uses_meteorological_boundaries() -> None:
    """Seasons follow month-based meteorological boundaries."""
    expected = (
        "WINTER",
        "WINTER",
        "SPRING",
        "SPRING",
        "SPRING",
        "SUMMER",
        "SUMMER",
        "SUMMER",
        "AUTUMN",
        "AUTUMN",
        "AUTUMN",
        "WINTER",
    )

    for month, season in enumerate(expected, start=1):
        assert clock_screens.season_name(month) == season


def test_time_seconds_screen_updates_each_second() -> None:
    """The large time screen includes seconds as visible content."""
    rtc = _FakeRTC()
    rtc.value = (2026, 6, 23, 1, 15, 59, 58, 0)
    first = clock_screens.screen_frame(clock_screens.SCREEN_TIME_SECONDS, rtc)
    rtc.value = (2026, 6, 23, 1, 15, 59, 59, 0)
    second = clock_screens.screen_frame(clock_screens.SCREEN_TIME_SECONDS, rtc)

    assert not _same_frame(first, second)
    assert clock_screens.key_from_rtc(clock_screens.SCREEN_TIME_SECONDS, rtc) == (
        clock_screens.SCREEN_TIME_SECONDS,
        15,
        59,
        59,
    )


def test_clock_meridiem_screen_fills_frame() -> None:
    """A short time scales up to fill the frame width next to a narrow meridiem."""
    rtc = _FakeRTC()
    rtc.value = (2026, 6, 23, 1, 9, 5, 0, 0)

    frame = clock_screens.screen_frame(clock_screens.SCREEN_CLOCK_MERIDIEM, rtc)
    unscaled_clock_width = Text("9:05", scale=(1, 1)).measure()[0]
    meridiem_width, meridiem_height = clock_screens._MeridiemBadge("AM").measure()
    side_by_side_meridiem_width = Text("AM").measure()[0]
    left, right, top, bottom = _lit_bounds(frame, 0, frame.height)

    # The time + meridiem span nearly the full width and nearly the full height.
    assert left == 0
    assert right >= frame.width - 2
    # The seconds bar row stays blank at :00, so the lit height is the meridiem.
    assert (top, bottom) == (0, frame.height - 2)
    # The time is scaled up past its 1:1 footprint while the meridiem stays narrow.
    assert right - left + 1 > unscaled_clock_width + meridiem_width
    assert meridiem_width < side_by_side_meridiem_width
    assert bottom - top + 1 == meridiem_height
    assert clock_screens.key_from_rtc(clock_screens.SCREEN_CLOCK_MERIDIEM, rtc) == (
        clock_screens.SCREEN_CLOCK_MERIDIEM,
        9,
        5,
        0,
    )


def test_clock_meridiem_screen_widest_time_stays_in_bounds() -> None:
    """The widest two-digit time still centers within the frame without overflow."""
    rtc = _FakeRTC()
    rtc.value = (2026, 6, 23, 1, 12, 59, 0, 0)

    frame = clock_screens.screen_frame(clock_screens.SCREEN_CLOCK_MERIDIEM, rtc)
    meridiem_width, meridiem_height = clock_screens._MeridiemBadge("PM").measure()
    side_by_side_meridiem_width = Text("PM").measure()[0]
    left, right, top, bottom = _lit_bounds(frame, 0, frame.height)

    assert left >= 0
    assert right <= frame.width - 1
    # Still horizontally centered (floor division leaves at most 1px of skew).
    assert 0 <= (frame.width - 1 - right) - left <= 1
    assert (top, bottom) == (0, frame.height - 2)
    assert meridiem_width < side_by_side_meridiem_width
    assert bottom - top + 1 == meridiem_height
    assert clock_screens.key_from_rtc(clock_screens.SCREEN_CLOCK_MERIDIEM, rtc) == (
        clock_screens.SCREEN_CLOCK_MERIDIEM,
        12,
        59,
        0,
    )


def test_seconds_free_faces_blink_the_colon_each_second() -> None:
    """The hour:minute faces drop the colon on odd seconds and key on it."""
    rtc = _FakeRTC()
    for screen in (clock_screens.SCREEN_MAIN, clock_screens.SCREEN_CLOCK_MERIDIEM):
        rtc.value = (2026, 6, 23, 1, 9, 5, 0, 0)
        colon_on = clock_screens.screen_frame(screen, rtc)
        rtc.value = (2026, 6, 23, 1, 9, 5, 1, 0)
        colon_off = clock_screens.screen_frame(screen, rtc)

        assert not _same_frame(colon_on, colon_off)
        assert _lit_count(colon_on) > _lit_count(colon_off)
        # The per-second key lets the engine re-render the blink while H:MM holds.
        assert clock_screens.screen_key(screen, (2026, 6, 23, 1, 9, 5, 1)) != (
            clock_screens.screen_key(screen, (2026, 6, 23, 1, 9, 5, 0))
        )


def test_seconds_progress_bar_fills_across_the_minute() -> None:
    """A seconds bar grows from blank at :00 to full width by :59 on free rows."""
    rows = {
        clock_screens.SCREEN_MAIN: (clock_screens.HEIGHT_PIXELS // 2) - 1,
        clock_screens.SCREEN_CLOCK_MERIDIEM: clock_screens.HEIGHT_PIXELS - 1,
    }
    rtc = _FakeRTC()
    for screen, row in rows.items():
        rtc.value = (2026, 6, 23, 1, 12, 30, 0, 0)
        assert _lit_row(clock_screens.screen_frame(screen, rtc), row) == 0
        rtc.value = (2026, 6, 23, 1, 12, 30, 59, 0)
        assert _lit_row(clock_screens.screen_frame(screen, rtc), row) == clock_screens.WIDTH_PIXELS

        counts = []
        for second in range(0, 60, 10):
            rtc.value = (2026, 6, 23, 1, 12, 30, second, 0)
            counts.append(_lit_row(clock_screens.screen_frame(screen, rtc), row))
        assert counts == sorted(counts)


def test_sync_uses_startup_timezone_offset(monkeypatch: pytest.MonkeyPatch) -> None:
    """GPS fixes reuse the timezone lookup from the first complete fix."""
    calls: list[tuple] = []
    emitted: list[dict] = []
    rtc = _FakeRTC()
    state: dict = {}
    clock = _ManualTime()

    def _offset(date_str: str, utc_str: str, lat: float, lon: float) -> tuple:
        calls.append((date_str, utc_str, lat, lon))
        return -25_200, "PDT"

    monkeypatch.setattr(clock_sync, "offset_seconds_from_gps", _offset)

    clock_sync.sync_from_line(_RMC_FIX, rtc, state, lambda obj: emitted.append(dict(obj)), clock)
    clock_sync.sync_from_line(_RMC_FIX, rtc, state, lambda obj: emitted.append(dict(obj)), clock)

    assert len(calls) == 1
    assert state["offset_s"] == -25_200
    assert state["tz_abbrev"] == "PDT"
    assert emitted[-1]["local"] == "2026-06-23T16:59:58"


def test_clock_hardware_opens_devices_and_flips_live_display() -> None:
    """ClockHardware owns construction and BOOT-button display flips."""
    board = SimpleNamespace(
        uart=SimpleNamespace(bus_id=0, tx=0, rx=1),
        display=SimpleNamespace(
            spi_id=1,
            sck=26,
            mosi=27,
            cs=28,
            surface=SimpleNamespace(width_pixels=32, height_pixels=16, brightness=0.2),
        ),
    )
    created: dict = {}

    def _display(**kwargs: object) -> _FakeDisplay:
        created["display"] = dict(kwargs)
        return _FakeDisplay()

    def _gps(**kwargs: object) -> _FakeGPS:
        created["gps"] = dict(kwargs)
        return _FakeGPS([])

    hardware = clock_hardware.ClockHardware(board, _display, _gps, _FakeRTC)

    hardware.flip_display()
    devices = hardware.open()
    hardware.flip_display()

    assert created["display"] == {
        "spi_id": 1,
        "sck": 26,
        "mosi": 27,
        "cs": 28,
        "width_pixels": 32,
        "height_pixels": 16,
        "brightness": 0.2,
    }
    assert created["gps"] == {"bus_id": 0, "tx": 0, "rx": 1}
    assert devices.display is hardware.display
    assert devices.display.flips == 1
    assert isinstance(devices.rtc, _FakeRTC)


def test_display_cycle_starts_main_and_updates_each_minute() -> None:
    """The synced display starts on the main screen and refreshes when visible time changes."""
    clock = _ManualTime()
    display = _FakeDisplay()
    rtc = _FakeRTC()
    cycle = clock_cycle.DisplayCycle(display, rtc, clock=clock)

    rtc.value = (2026, 6, 23, 1, 0, 5, 58, 0)
    cycle.tick(synced=True)
    rtc.value = (2026, 6, 23, 1, 0, 5, 59, 0)
    cycle.tick(synced=True)
    rtc.value = (2026, 6, 23, 1, 0, 6, 0, 0)
    cycle.tick(synced=True)

    assert cycle.current_screen == clock_screens.SCREEN_MAIN
    assert len(display.shown) == 2
    rtc.value = (2026, 6, 23, 1, 0, 5, 58, 0)
    assert _same_frame(
        display.shown[0],
        clock_screens.screen_frame(clock_screens.SCREEN_MAIN, rtc),
    )
    rtc.value = (2026, 6, 23, 1, 0, 6, 0, 0)
    assert _same_frame(
        display.shown[1],
        clock_screens.screen_frame(clock_screens.SCREEN_MAIN, rtc),
    )


def test_month_abbreviations_fit_main_date_row() -> None:
    """Month abbreviations fit with the largest day on the main date row."""
    for month, label in enumerate(clock_screens.MONTH_ABBRS, start=1):
        assert clock_screens.format_month_abbr(month) == label
        assert Text(f"{label} 31").measure()[0] <= 32


def test_two_row_frame_centers_compact_month_date() -> None:
    """The month row uses compact glyphs centered in the lower display band."""
    frame = clock_screens._two_row_frame("12:05 AM", "June 23", 32, 16)
    month_width = Text("June 23").measure()[0]
    left, right, top, bottom = _lit_bounds(frame, 8, 16)

    assert left == (frame.width - month_width) // 2
    assert right == left + month_width - 1
    assert (top, bottom) == (9, 15)
    assert all(frame.value_at(x, 7) == 0 for x in range(frame.width))
    assert all(frame.value_at(x, 8) == 0 for x in range(frame.width))


def test_random_screen_and_transition_choices() -> None:
    """Random helpers choose a non-current screen and a valid effect."""
    screens = clock_screens.REGULAR_SCREENS

    assert clock_screens.choose_next_regular(screens[0], _FakeRandom([0])) == screens[1]
    assert clock_screens.choose_next_regular(screens[0], _FakeRandom([1])) == screens[2]
    assert clock_screens.choose_next_regular(screens[0], _FakeRandom([255])) == screens[2]
    for current in screens:
        assert clock_screens.choose_next_regular(current, _FakeRandom([255])) != current

    assert (
        clock_transitions.choose_transition(_FakeRandom([0])) == clock_transitions.TRANSITION_WIPE
    )
    assert (
        clock_transitions.choose_transition(_FakeRandom([1]))
        == clock_transitions.TRANSITION_DISSOLVE
    )
    assert (
        clock_transitions.choose_transition(_FakeRandom([2])) == clock_transitions.TRANSITION_SCROLL
    )
    assert (
        clock_transitions.choose_transition(_FakeRandom([3]))
        == clock_transitions.TRANSITION_INSTANT
    )


def test_display_cycle_holds_regular_screens_for_three_minutes() -> None:
    """The manager waits 180 seconds before starting a random transition."""
    clock = _ManualTime()
    display = _FakeDisplay()
    rtc = _FakeRTC()
    rtc.value = (2026, 6, 23, 1, 16, 59, 58, 0)
    cycle = clock_cycle.DisplayCycle(
        display,
        rtc,
        clock=clock,
        rng=_FakeRandom([0, 0]),
    )

    cycle.tick(synced=True)
    start = cycle.screen_started_ms
    clock.ticks = start + clock_screens.SCREEN_HOLD_MS - 2
    cycle.tick(synced=True)

    assert cycle.current_screen == clock_screens.SCREEN_MAIN
    assert cycle.transition is None

    clock.ticks = start + clock_screens.SCREEN_HOLD_MS - 1
    cycle.tick(synced=True)

    assert cycle.current_screen == clock_screens.SCREEN_MAIN
    assert cycle.transition.target_screen == clock_screens.SCREEN_SEASON
    assert cycle.transition.effect == clock_transitions.TRANSITION_WIPE


def test_transition_completion_sets_target_and_restarts_hold() -> None:
    """A transition advances one frame per call and lands exactly on target."""
    clock = _ManualTime()
    display = _FakeDisplay()
    rtc = _FakeRTC()
    rtc.value = (2026, 6, 23, 1, 16, 59, 58, 0)
    cycle = clock_cycle.DisplayCycle(
        display,
        rtc,
        clock=clock,
        rng=_FakeRandom([0, 0]),
    )

    cycle.tick(synced=True)
    cycle._start_next_screen_transition()
    while cycle.transition is not None:
        cycle._advance_transition(clock.ticks_ms())

    assert cycle.current_screen == clock_screens.SCREEN_SEASON
    assert cycle.screen_started_ms == clock.ticks
    assert _same_frame(display.shown[-1], cycle.screen_frame)


def test_instant_transition_lands_on_target_in_one_render() -> None:
    """Instant transitions show the target and finish after one display update."""
    clock = _ManualTime()
    display = _FakeDisplay()
    rtc = _FakeRTC()
    rtc.value = (2026, 6, 23, 1, 16, 59, 58, 0)
    cycle = clock_cycle.DisplayCycle(
        display,
        rtc,
        clock=clock,
        rng=_FakeRandom([0, 3]),
    )

    cycle.tick(synced=True)
    cycle._start_next_screen_transition()
    cycle._advance_transition(clock.ticks_ms())

    assert cycle.transition is None
    assert cycle.current_screen == clock_screens.SCREEN_SEASON
    assert cycle.shown_key == clock_screens.key_from_rtc(clock_screens.SCREEN_SEASON, rtc)
    assert _same_frame(
        display.shown[-1],
        clock_screens.screen_frame(clock_screens.SCREEN_SEASON, rtc),
    )


def test_transition_snapshots_endpoints_and_refreshes_target_after_landing() -> None:
    """Transitions use snapshotted endpoints and refresh changed target content after landing."""
    clock = _ManualTime()
    display = _FakeDisplay()
    rtc = _FakeRTC()
    rtc.value = (2026, 6, 23, 1, 15, 59, 58, 0)
    cycle = clock_cycle.DisplayCycle(
        display,
        rtc,
        clock=clock,
        rng=_FakeRandom([0, 0]),
    )
    old_parts = clock_screens.rtc_parts(rtc)

    cycle._show_screen(clock_screens.SCREEN_TIME_SECONDS, clock.ticks_ms())
    cycle._start_transition(
        clock_screens.SCREEN_TIME_SECONDS,
        clock_screens.SCREEN_SEASON,
        clock_transitions.TRANSITION_STEPS,
    )
    cycle.transition.step = 1
    rtc.value = (2026, 6, 23, 1, 15, 59, 59, 0)
    cycle._advance_transition(clock.ticks_ms())

    expected_source = clock_screens.render_screen(clock_screens.SCREEN_TIME_SECONDS, old_parts)
    expected_target = clock_screens.render_screen(clock_screens.SCREEN_SEASON, old_parts)
    assert _same_frame(
        display.shown[-1],
        clock_transitions.wipe_frame(
            expected_source,
            expected_target,
            1,
            clock_transitions.TRANSITION_STEPS,
        ),
    )

    display = _FakeDisplay()
    clock = _ManualTime()
    rtc.value = (2026, 6, 23, 1, 15, 59, 58, 0)
    cycle = clock_cycle.DisplayCycle(display, rtc, clock=clock, rng=_FakeRandom([0]))
    cycle._show_screen(clock_screens.SCREEN_SEASON, clock.ticks_ms())
    cycle._start_transition(
        clock_screens.SCREEN_SEASON,
        clock_screens.SCREEN_TIME_SECONDS,
        clock_transitions.TRANSITION_STEPS,
    )
    cycle.transition.step = cycle.transition.steps
    shown_before_landing = len(display.shown)
    rtc.value = (2026, 6, 23, 1, 15, 59, 59, 0)
    cycle._advance_transition(clock.ticks_ms())

    assert cycle.current_screen == clock_screens.SCREEN_TIME_SECONDS
    assert cycle.shown_key == (clock_screens.SCREEN_TIME_SECONDS, 15, 59, 59)
    assert len(display.shown) == shown_before_landing + 2
    assert _same_frame(
        display.shown[-1],
        clock_screens.screen_frame(clock_screens.SCREEN_TIME_SECONDS, rtc),
    )


def test_dissolve_frame_lands_on_target() -> None:
    """Dissolve transitions land exactly on the target endpoint."""
    source = Frame(4, 2)
    target = Frame(4, 2)
    for index in range(len(target.data)):
        target.data[index] = 255

    assert _same_frame(
        clock_transitions.dissolve_frame(
            source,
            target,
            clock_transitions.TRANSITION_STEPS,
            clock_transitions.TRANSITION_STEPS,
        ),
        target,
    )


def test_run_reports_read_errors_and_keeps_loop_alive(main_ns: object) -> None:
    """UART/parser exceptions emit a diagnostic and use the read-error LED state."""
    main_ns.ns["time"] = _CountdownTime(stop_after=1)
    emitted: list[dict] = []
    main_ns.ns["emit"] = lambda obj: emitted.append(dict(obj))

    with pytest.raises(_StopLoop):
        main_ns.ns["run"](_FakeGPS([OSError("uart")]), _FakeDisplay(), _FakeRTC())

    assert {"diag": "read_err"} in emitted
    assert "read_err" in main_ns.status.calls


def test_main_reports_init_error_and_retries(main_ns: object) -> None:
    """main() emits init_err and retries when GPS/display setup fails."""
    main_ns.ns["time"] = _CountdownTime(stop_after=2)
    emitted: list[dict] = []
    main_ns.ns["emit"] = lambda obj: emitted.append(dict(obj))

    def _boom(**_kwargs: object) -> None:
        raise OSError("no display")

    main_ns.ns["MAX7219"] = _boom

    with pytest.raises(_StopLoop):
        main_ns.ns["main"]()

    assert {"diag": "init_err"} in emitted
    assert "init_err" in main_ns.status.calls


def test_main_runs_after_successful_init(main_ns: object) -> None:
    """main() wires board pins into the GPS, display, RTC, and run loop."""
    main_ns.ns["time"] = _CountdownTime(stop_after=99)
    main_ns.ns["emit"] = lambda _obj: None
    created: dict = {}

    def _display(**kwargs: object) -> _FakeDisplay:
        created["display"] = dict(kwargs)
        return _FakeDisplay()

    def _gps(**kwargs: object) -> _FakeGPS:
        created["gps"] = dict(kwargs)
        return _FakeGPS([])

    def _run(gps: object, display: object, rtc: object) -> None:
        created["run"] = (gps, display, rtc)
        raise _StopLoop

    main_ns.ns["MAX7219"] = _display
    main_ns.ns["GPS"] = _gps
    main_ns.ns["RTC"] = _FakeRTC
    main_ns.ns["run"] = _run

    with pytest.raises(_StopLoop):
        main_ns.ns["main"]()

    assert created["display"] == {
        "spi_id": 1,
        "sck": 26,
        "mosi": 27,
        "cs": 28,
        "width_pixels": 32,
        "height_pixels": 16,
        "brightness": 0.2,
    }
    assert created["gps"] == {"bus_id": 0, "tx": 0, "rx": 1}
    assert isinstance(created["run"][2], _FakeRTC)


def _same_frame(left: object, right: object) -> bool:
    """Return whether two frame-like objects hold identical pixels."""
    if left.width != right.width or left.height != right.height or left.channels != right.channels:
        return False
    for y in range(left.height):
        for x in range(left.width):
            for channel in range(left.channels):
                if left.value_at(x, y, channel) != right.value_at(x, y, channel):
                    return False
    return True


def _lit_count(frame: object) -> int:
    """Return the number of lit pixels in a frame."""
    return sum(1 for y in range(frame.height) for x in range(frame.width) if frame.value_at(x, y))


def _lit_row(frame: object, y: int) -> int:
    """Return the number of lit pixels in one frame row."""
    return sum(1 for x in range(frame.width) if frame.value_at(x, y))


def _lit_bounds(frame: object, y0: int, y1: int) -> tuple:
    """Return inclusive lit-pixel bounds inside a vertical slice."""
    xs = []
    ys = []
    for y in range(y0, y1):
        for x in range(frame.width):
            if frame.value_at(x, y):
                xs.append(x)
                ys.append(y)
    return min(xs), max(xs), min(ys), max(ys)
