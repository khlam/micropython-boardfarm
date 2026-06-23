"""Host CPython tests for the clock project firmware."""

from __future__ import annotations

import json

import pytest

from pixel_display import Frame

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


class _FakeDisplay:
    """Display stand-in recording abstract frame renders."""

    def __init__(self) -> None:
        """Initialise an empty call log."""
        self.shown: list[object] = []

    def show(self, frame: object) -> None:
        """Record the requested frame."""
        self.shown.append(frame)


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


def test_emit_writes_one_json_line(
    main_ns: object,
    capsys: pytest.CaptureFixture,
) -> None:
    """emit() writes exactly one compact JSON object per line."""
    main_ns.ns["emit"]({"fix": True, "day": "TUE"})
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
        main_ns.ns["_wipe_frame"](
            main_ns.ns["_blank_wait_frame"](),
            main_ns.ns["_wait_frame"](),
            1,
            main_ns.ns["_WAIT_TRANSITION_STEPS"],
        ),
    )
    assert "streaming" in main_ns.status.calls


def test_wait_screen_transitions_off_after_one_second(main_ns: object) -> None:
    """The unsynced wait display flips between visible and blank endpoints."""
    main_ns.ns["random"] = _FakeRandom([3, 3])
    display = _FakeDisplay()
    rtc = _FakeRTC()
    state = {"synced": False, "intensity_limit": 0.2}

    main_ns.ns["_refresh_display"](display, rtc, state)
    assert state["wait_visible"] is True
    assert _same_frame(display.shown[-1], main_ns.ns["_wait_frame"]())

    phase_started = state["wait_phase_started_ms"]
    main_ns.time.ticks = phase_started + main_ns.ns["_WAIT_ROTATE_MS"] - 2
    main_ns.ns["_refresh_display"](display, rtc, state)
    assert len(display.shown) == 1

    main_ns.time.ticks = phase_started + main_ns.ns["_WAIT_ROTATE_MS"] - 1
    main_ns.ns["_refresh_display"](display, rtc, state)
    assert state["wait_visible"] is False
    assert _same_frame(display.shown[-1], main_ns.ns["_blank_wait_frame"]())


def test_wait_screen_holds_after_slow_transition_lands(main_ns: object) -> None:
    """A long GPS wait transition starts its hold timer when it lands."""
    main_ns.ns["random"] = _FakeRandom([0])
    display = _FakeDisplay()
    state: dict = {"intensity_limit": 0.2}
    started = 100
    landed = started + main_ns.ns["_WAIT_ROTATE_MS"]

    main_ns.ns["_start_wait_transition"](state)
    state["wait_transition"]["step"] = state["wait_transition"]["steps"]
    main_ns.ns["_advance_wait_transition"](display, state, landed)

    assert state["wait_visible"] is True
    assert state["wait_phase_started_ms"] == landed
    shown_count = len(display.shown)
    main_ns.ns["random"] = _FakeRandom([])
    main_ns.time.ticks = landed + main_ns.ns["_WAIT_ROTATE_MS"] - 2
    main_ns.ns["_refresh_display"](display, _FakeRTC(), state)

    assert state["wait_transition"] is None
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
        main_ns.ns["_screen_frame"](main_ns.ns["_SCREEN_MAIN"], rtc),
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


def test_screen_renderers_fit_the_matrix(main_ns: object) -> None:
    """Every display-cycle screen renders to the fixed 32x16 frame surface."""
    rtc = _FakeRTC()
    rtc.value = (2026, 5, 31, 6, 23, 59, 58, 0)

    for screen in main_ns.ns["_SCREENS"] + main_ns.ns["_INTERSTITIALS"]:
        frame = main_ns.ns["_screen_frame"](screen, rtc)
        assert (frame.width, frame.height, frame.channels) == (32, 16, 1)
        assert any(frame.data)

    for month in range(1, 13):
        month_name = main_ns.ns["_MONTH_NAMES"][month - 1]
        season = main_ns.ns["_season_name"](month)
        assert main_ns.ns["_compact_text_width"](month_name) <= 32
        assert main_ns.ns["_compact_text_width"](season) <= 32


def test_season_name_uses_meteorological_boundaries(main_ns: object) -> None:
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
        assert main_ns.ns["_season_name"](month) == season


def test_time_seconds_screen_updates_each_second(main_ns: object) -> None:
    """The large time screen includes seconds as visible content."""
    rtc = _FakeRTC()
    rtc.value = (2026, 6, 23, 1, 15, 59, 58, 0)
    first = main_ns.ns["_screen_frame"](main_ns.ns["_SCREEN_TIME_SECONDS"], rtc)
    rtc.value = (2026, 6, 23, 1, 15, 59, 59, 0)
    second = main_ns.ns["_screen_frame"](main_ns.ns["_SCREEN_TIME_SECONDS"], rtc)

    assert not _same_frame(first, second)
    assert main_ns.ns["_screen_key"](main_ns.ns["_SCREEN_TIME_SECONDS"], rtc) == (
        main_ns.ns["_SCREEN_TIME_SECONDS"],
        15,
        59,
        59,
    )


def test_clock_meridiem_screen_centers_tall_time(main_ns: object) -> None:
    """The clock-only screen centers large time next to a smaller meridiem."""
    rtc = _FakeRTC()
    rtc.value = (2026, 6, 23, 1, 12, 59, 0, 0)

    frame = main_ns.ns["_screen_frame"](main_ns.ns["_SCREEN_CLOCK_MERIDIEM"], rtc)
    unscaled_clock_width = main_ns.ns["_compact_text_width"]("12:59")
    clock_width = main_ns.ns["_compact_text_width"](
        "12:59",
        main_ns.ns["_CLOCK_MERIDIEM_TIME_GAP_PIXELS"],
        main_ns.ns["_CLOCK_MERIDIEM_TIME_X_SCALE"],
    )
    meridiem_width = main_ns.ns["_compact_text_width"]("M", 0)
    side_by_side_meridiem_width = main_ns.ns["_compact_text_width"]("PM")
    group_width = clock_width + main_ns.ns["_CLOCK_MERIDIEM_LABEL_GAP_PIXELS"] + meridiem_width
    left, right, top, bottom = _lit_bounds(frame, 0, frame.height)

    assert clock_width > unscaled_clock_width
    assert meridiem_width < side_by_side_meridiem_width
    assert left == (frame.width - group_width) // 2
    assert right == left + group_width - 1
    assert (top, bottom) == (0, 14)
    assert bottom - top + 1 == (
        (2 * main_ns.ns["_COMPACT_GLYPH_HEIGHT"])
        + main_ns.ns["_CLOCK_MERIDIEM_LABEL_LINE_GAP_PIXELS"]
    )
    assert main_ns.ns["_screen_key"](main_ns.ns["_SCREEN_CLOCK_MERIDIEM"], rtc) == (
        main_ns.ns["_SCREEN_CLOCK_MERIDIEM"],
        12,
        59,
    )


def test_sync_uses_startup_timezone_offset(main_ns: object) -> None:
    """GPS fixes reuse the timezone lookup from the first complete fix."""
    calls: list[tuple] = []
    emitted: list[dict] = []
    rtc = _FakeRTC()
    state: dict = {}

    def _offset(date_str: str, utc_str: str, lat: float, lon: float) -> tuple:
        calls.append((date_str, utc_str, lat, lon))
        return -25_200, "PDT"

    main_ns.ns["offset_seconds_from_gps"] = _offset
    main_ns.ns["emit"] = lambda obj: emitted.append(dict(obj))

    main_ns.ns["_sync_from_line"](_RMC_FIX, rtc, state)
    main_ns.ns["_sync_from_line"](_RMC_FIX, rtc, state)

    assert len(calls) == 1
    assert state["offset_s"] == -25_200
    assert state["tz_abbrev"] == "PDT"
    assert emitted[-1]["local"] == "2026-06-23T16:59:58"


def test_refresh_display_starts_main_and_updates_each_minute(
    main_ns: object,
) -> None:
    """The synced display starts on the main screen and refreshes when visible time changes."""
    display = _FakeDisplay()
    rtc = _FakeRTC()
    state = {"synced": True, "intensity_limit": 0.2}

    rtc.value = (2026, 6, 23, 1, 0, 5, 58, 0)
    main_ns.ns["_refresh_display"](display, rtc, state)
    rtc.value = (2026, 6, 23, 1, 0, 5, 59, 0)
    main_ns.ns["_refresh_display"](display, rtc, state)
    rtc.value = (2026, 6, 23, 1, 0, 6, 0, 0)
    main_ns.ns["_refresh_display"](display, rtc, state)

    assert state["screen"] == main_ns.ns["_SCREEN_MAIN"]
    assert len(display.shown) == 2
    rtc.value = (2026, 6, 23, 1, 0, 5, 58, 0)
    assert _same_frame(
        display.shown[0],
        main_ns.ns["_screen_frame"](main_ns.ns["_SCREEN_MAIN"], rtc),
    )
    rtc.value = (2026, 6, 23, 1, 0, 6, 0, 0)
    assert _same_frame(
        display.shown[1],
        main_ns.ns["_screen_frame"](main_ns.ns["_SCREEN_MAIN"], rtc),
    )


def test_month_abbreviations_fit_main_date_row(main_ns: object) -> None:
    """Month abbreviations fit with the largest day on the main date row."""
    for month, label in enumerate(main_ns.ns["_MONTH_ABBRS"], start=1):
        assert main_ns.ns["_format_month_abbr"](month) == label
        assert main_ns.ns["_compact_text_width"](f"{label} 31") <= 32


def test_clock_face_centers_compact_month_date(main_ns: object) -> None:
    """The month row uses compact glyphs centered in the lower display band."""
    frame = main_ns.ns["_display_frame"]("12:05 AM", "June 23", colon_visible=True)
    month_width = main_ns.ns["_compact_text_width"]("June 23")
    left, right, top, bottom = _lit_bounds(frame, 8, 16)

    assert month_width < Frame.text("June 23").width
    assert left == (frame.width - month_width) // 2
    assert right == left + month_width - 1
    assert (top, bottom) == (9, 15)
    assert all(frame.value_at(x, 7) == 0 for x in range(frame.width))
    assert all(frame.value_at(x, 8) == 0 for x in range(frame.width))


def test_random_screen_and_transition_choices(main_ns: object) -> None:
    """Random helpers choose a non-current screen and a valid effect."""
    screens = main_ns.ns["_SCREENS"]

    assert main_ns.ns["_choose_next_screen"](screens[0], _FakeRandom([0])) == screens[1]
    assert main_ns.ns["_choose_next_screen"](screens[0], _FakeRandom([1])) == screens[2]
    assert main_ns.ns["_choose_next_screen"](screens[0], _FakeRandom([255])) == screens[2]
    for current in screens:
        assert main_ns.ns["_choose_next_screen"](current, _FakeRandom([255])) != current

    assert main_ns.ns["_choose_transition"](_FakeRandom([0])) == main_ns.ns["_TRANSITION_WIPE"]
    assert main_ns.ns["_choose_transition"](_FakeRandom([1])) == main_ns.ns["_TRANSITION_FADE"]
    assert main_ns.ns["_choose_transition"](_FakeRandom([2])) == main_ns.ns["_TRANSITION_SCROLL"]
    assert main_ns.ns["_choose_transition"](_FakeRandom([3])) == main_ns.ns["_TRANSITION_INSTANT"]


def test_refresh_display_holds_each_screen_for_three_minutes(main_ns: object) -> None:
    """The manager waits 180 seconds before starting a random transition."""
    main_ns.ns["random"] = _FakeRandom([0, 0])
    display = _FakeDisplay()
    rtc = _FakeRTC()
    rtc.value = (2026, 6, 23, 1, 16, 59, 58, 0)
    state = {"synced": True, "intensity_limit": 0.2}

    main_ns.ns["_refresh_display"](display, rtc, state)
    start = state["screen_started_ms"]
    main_ns.time.ticks = start + main_ns.ns["_SCREEN_HOLD_MS"] - 2
    main_ns.ns["_refresh_display"](display, rtc, state)

    assert state["screen"] == main_ns.ns["_SCREEN_MAIN"]
    assert state["transition"] is None

    main_ns.time.ticks = start + main_ns.ns["_SCREEN_HOLD_MS"] - 1
    main_ns.ns["_refresh_display"](display, rtc, state)

    assert state["screen"] == main_ns.ns["_SCREEN_MAIN"]
    assert state["transition"]["target_screen"] == main_ns.ns["_SCREEN_SEASON"]
    assert state["transition"]["effect"] == main_ns.ns["_TRANSITION_WIPE"]


def test_transition_completion_sets_target_and_restarts_hold(main_ns: object) -> None:
    """A transition advances one frame per call and lands exactly on target."""
    main_ns.ns["random"] = _FakeRandom([0, 0])
    display = _FakeDisplay()
    rtc = _FakeRTC()
    rtc.value = (2026, 6, 23, 1, 16, 59, 58, 0)
    state = {"synced": True, "intensity_limit": 0.2}

    main_ns.ns["_start_screen_cycle"](display, rtc, state, main_ns.time.ticks_ms())
    main_ns.ns["_start_transition"](state)
    while state["transition"] is not None:
        main_ns.ns["_advance_transition"](display, rtc, state, main_ns.time.ticks_ms())

    assert state["screen"] == main_ns.ns["_SCREEN_SEASON"]
    assert state["screen_started_ms"] == main_ns.time.ticks
    assert _same_frame(display.shown[-1], state["screen_frame"])


def test_instant_transition_lands_on_target_in_one_render(main_ns: object) -> None:
    """Instant transitions show the target and finish after one display update."""
    main_ns.ns["random"] = _FakeRandom([0, 3])
    display = _FakeDisplay()
    rtc = _FakeRTC()
    rtc.value = (2026, 6, 23, 1, 16, 59, 58, 0)
    state = {"synced": True, "intensity_limit": 0.2}

    main_ns.ns["_start_screen_cycle"](display, rtc, state, main_ns.time.ticks_ms())
    main_ns.ns["_start_transition"](state)
    main_ns.ns["_advance_transition"](display, rtc, state, main_ns.time.ticks_ms())

    assert state["transition"] is None
    assert state["screen"] == main_ns.ns["_SCREEN_SEASON"]
    assert state["shown"] == main_ns.ns["_screen_key"](main_ns.ns["_SCREEN_SEASON"], rtc)
    assert _same_frame(
        display.shown[-1],
        main_ns.ns["_screen_frame"](main_ns.ns["_SCREEN_SEASON"], rtc),
    )


def test_transition_renders_live_source_and_target(main_ns: object) -> None:
    """Transitions re-render both endpoint screens from the current RTC value."""
    display = _FakeDisplay()
    rtc = _FakeRTC()
    steps = main_ns.ns["_TRANSITION_STEPS"]

    rtc.value = (2026, 6, 23, 1, 15, 59, 58, 0)
    main_ns.ns["random"] = _FakeRandom([0, 0])
    state = {
        "synced": True,
        "screen": main_ns.ns["_SCREEN_TIME_SECONDS"],
        "screen_frame": main_ns.ns["_screen_frame"](
            main_ns.ns["_SCREEN_TIME_SECONDS"],
            rtc,
        ),
        "intensity_limit": 0.2,
    }
    main_ns.ns["_start_transition"](state)
    state["transition"]["step"] = 1
    rtc.value = (2026, 6, 23, 1, 15, 59, 59, 0)
    main_ns.ns["_advance_transition"](display, rtc, state, main_ns.time.ticks_ms())

    expected_source = main_ns.ns["_screen_frame"](
        main_ns.ns["_SCREEN_TIME_SECONDS"],
        rtc,
    )
    expected_target = main_ns.ns["_screen_frame"](
        main_ns.ns["_SCREEN_SEASON"],
        rtc,
    )
    assert _same_frame(
        display.shown[-1],
        main_ns.ns["_wipe_frame"](expected_source, expected_target, 1, steps),
    )

    display = _FakeDisplay()
    rtc.value = (2026, 6, 23, 1, 15, 59, 58, 0)
    main_ns.ns["random"] = _FakeRandom([1, 0])
    state = {
        "synced": True,
        "screen": main_ns.ns["_SCREEN_SEASON"],
        "prev_regular": main_ns.ns["_SCREEN_MAIN"],
        "intensity_limit": 0.2,
    }
    main_ns.ns["_start_transition"](state)
    state["transition"]["step"] = steps
    rtc.value = (2026, 6, 23, 1, 15, 59, 59, 0)
    main_ns.ns["_advance_transition"](display, rtc, state, main_ns.time.ticks_ms())

    assert state["screen"] == main_ns.ns["_SCREEN_TIME_SECONDS"]
    assert state["shown"] == (
        main_ns.ns["_SCREEN_TIME_SECONDS"],
        15,
        59,
        59,
    )
    assert _same_frame(
        display.shown[-1],
        main_ns.ns["_screen_frame"](main_ns.ns["_SCREEN_TIME_SECONDS"], rtc),
    )


def test_low_intensity_fade_starts_at_minimum_visible_byte(main_ns: object) -> None:
    """Fade-in starts at the lowest byte expected to survive display capping."""
    source = Frame.blank(4, 2)
    target = Frame.blank(4, 2)
    for index in range(len(target.data)):
        target.data[index] = 255
    intensity_limit = 0.01
    min_visible = main_ns.ns["_min_visible_source_byte"](intensity_limit)

    first_visible = main_ns.ns["_fade_frame"](
        source,
        target,
        (main_ns.ns["_TRANSITION_STEPS"] // 2) + 1,
        main_ns.ns["_TRANSITION_STEPS"],
        intensity_limit,
    )
    values = [
        first_visible.value_at(x, y)
        for y in range(first_visible.height)
        for x in range(first_visible.width)
        if first_visible.value_at(x, y)
    ]

    assert values
    assert set(values) == {min_visible}
    assert _same_frame(
        main_ns.ns["_fade_frame"](
            source,
            target,
            main_ns.ns["_TRANSITION_STEPS"],
            main_ns.ns["_TRANSITION_STEPS"],
            intensity_limit,
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
        "intensity_limit": 0.2,
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
