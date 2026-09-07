"""Host CPython tests for the clock screen table and its renderers.

Every screen renders into the fixed 32x16 packed surface, and its content key
must change exactly when the visible pixels do — that key is what drives the
engine's re-render, so a key that misses a field freezes the display. Layout
assertions target the tight cases (widest time, longest month label) where the
glyphs come closest to overflowing the matrix.
"""

from __future__ import annotations

import pytest
from fake_clock import FakeRandom, FakeRTC, lit_bounds, lit_count, lit_row, same_frame

import clock_screens
from pixel_frame import Frame, Text

_RTC_VALUE = (2026, 5, 31, 6, 23, 59, 58, 0)

_ALL_SCREENS = tuple(spec.id for spec in clock_screens.SCREEN_SPECS)
_PARTS = (2026, 5, 31, 6, 23, 59, 58)


@pytest.mark.parametrize("screen", _ALL_SCREENS)
def test_every_screen_renders_content_in_the_matrix_geometry(screen: int) -> None:
    frame = clock_screens.render_screen(screen, _parts_for(screen))

    assert isinstance(frame, Frame)
    assert (frame.width, frame.height, frame.channels) == (32, 16, 1)
    assert (lit_count(frame) > 0) is (screen != clock_screens.WAIT_OFF)


@pytest.mark.parametrize("screen", _ALL_SCREENS)
def test_every_screen_survives_a_display_too_short_for_two_rows(screen: int) -> None:
    """A one-pixel-high panel must render blank, not raise or draw out of bounds.

    Geometry comes from the display object, so a mis-wired or differently sized
    panel reaches the renderers directly. Every row split, seconds bar and
    marquee has a degenerate branch for it and none of them is otherwise taken.
    """
    frame = clock_screens.render_screen(screen, _parts_for(screen), 32, 1)

    assert (frame.width, frame.height) == (32, 1)
    # Nothing fits in one row: the glyphs are seven tall, so every screen but
    # the diagnostic trace (which draws raw pixels) comes out dark.
    if screen != clock_screens.SCREEN_FRAME_RATE:
        assert lit_count(frame) == 0


def test_time_only_face_falls_back_to_one_row_when_the_badge_crowds_it_out() -> None:
    """Below ~6px wide there is no room beside the meridiem badge for any time."""
    frame = clock_screens.render_screen(clock_screens.SCREEN_CLOCK_MERIDIEM, _PARTS, 5, 16)

    assert (frame.width, frame.height) == (5, 16)
    assert lit_count(frame) == 0


def test_meridiem_badge_refuses_a_box_it_cannot_fit() -> None:
    """The badge draws nothing rather than spilling outside its assigned box."""
    badge = clock_screens._MeridiemBadge("AM")
    width, height = badge.measure()
    frame = Frame(32, 16)

    badge.draw(frame, 0, 0, width - 1, height)
    badge.draw(frame, 0, 0, width, height - 1)

    assert lit_count(frame) == 0


def test_meridiem_badge_skips_letters_it_has_no_glyph_for() -> None:
    """Only A, M and P are drawn; anything else is silently omitted."""
    frame = Frame(32, 16)

    clock_screens._MeridiemBadge("AZ").draw(frame, 0, 0, 32, 16)

    only_a = Frame(32, 16)
    clock_screens._MeridiemBadge("A").draw(only_a, 0, 0, 32, 16)
    assert lit_count(frame) == lit_count(only_a)


def test_rtc_parts_drops_the_subsecond_field() -> None:
    """Renderers key off whole seconds, so the RTC's subsecond must not leak in."""
    assert clock_screens.rtc_parts(FakeRTC(_RTC_VALUE)) == _RTC_VALUE[:7]


@pytest.mark.parametrize("screen", _ALL_SCREENS)
def test_only_the_gps_endpoints_are_wait_screens(screen: int) -> None:
    """`is_wait` drives both the engine's step budget and its parts lookup."""
    expected = screen in (clock_screens.WAIT_ON, clock_screens.WAIT_OFF)

    assert clock_screens.is_wait(screen) is expected


def test_screen_spec_rejects_an_unknown_screen() -> None:
    with pytest.raises(KeyError):
        clock_screens.screen_spec(999)


@pytest.mark.parametrize(
    "hour,expected",
    [
        (0, ("12:05", "AM")),  # midnight reads as 12, not 0
        (9, ("9:05", "AM")),
        (12, ("12:05", "PM")),  # noon flips the meridiem but keeps 12
        (13, ("1:05", "PM")),
        (23, ("11:05", "PM")),
    ],
)
def test_format_time_parts_wraps_to_a_12_hour_clock(hour: int, expected: tuple) -> None:
    assert clock_screens.format_time_parts(hour, 5) == expected


def test_format_time_seconds_appends_zero_padded_seconds() -> None:
    assert clock_screens.format_time_seconds(13, 5, 7) == "1:05:07"


@pytest.mark.parametrize(
    "month,expected",
    [
        (1, "WINTER"),
        (2, "WINTER"),
        (3, "SPRING"),  # meteorological spring starts in March, not at the equinox
        (5, "SPRING"),
        (6, "SUMMER"),
        (8, "SUMMER"),
        (9, "AUTUMN"),
        (11, "AUTUMN"),
        (12, "WINTER"),
    ],
)
def test_season_name_uses_meteorological_boundaries(month: int, expected: str) -> None:
    assert clock_screens.season_name(month) == expected


def test_month_abbreviations_fit_beside_the_widest_day() -> None:
    """Every abbreviation must fit "<MONTH> 31" inside the 32px matrix."""
    for month in range(1, 13):
        label = clock_screens.format_month_abbr(month)
        assert Text(f"{label} 31").measure()[0] <= clock_screens.WIDTH_PIXELS


@pytest.mark.parametrize("day", [1, 9, 31], ids=["one-digit", "nine", "widest"])
@pytest.mark.parametrize("month", range(1, 13))
def test_full_date_always_draws_a_month_label_that_fits(month: int, day: int) -> None:
    """No month/day pair may pick a label too wide to draw.

    `Text` refuses to render content wider than its box and draws *nothing*, so
    an overlong label does not overflow — it blanks the row. Only MAY and SEPT
    are covered elsewhere, which leaves the long names (SEPTEMBER, NOVEMBER)
    untested against the widest day.
    """
    frame = clock_screens.render_screen(
        clock_screens.SCREEN_FULL_DATE, (2026, month, day, 0, 0, 0, 0)
    )

    assert _band(frame, 0, 8), (month, day)


@pytest.mark.parametrize(
    "day,expected",
    [(1, "AUGUST 1"), (31, "AUG 31")],
    ids=["full-name-fits", "abbreviated"],
)
def test_full_date_prefers_the_whole_month_name_while_it_still_fits(
    day: int, expected: str
) -> None:
    """August is the month that changes its mind: the full name fits day 1, not 31."""
    frame = clock_screens.render_screen(clock_screens.SCREEN_FULL_DATE, (2026, 8, day, 0, 0, 0, 0))
    labelled = Frame(32, 16)
    labelled[0:8, 0:32] = Text(expected)

    assert _band(frame, 0, 8) == _band(labelled, 0, 8)


@pytest.mark.parametrize("weekday", range(7))
def test_compact_face_names_every_day_of_the_week(weekday: int) -> None:
    """`DAYS[weekday]` is indexed straight off the RTC; only SUN is covered above."""
    parts = (2026, 5, 31, weekday, 23, 59, 0)
    frame = clock_screens.render_screen(clock_screens.SCREEN_MAIN, parts)
    named = Frame(32, 16)
    named[8:16, 0:32] = Text(f"{clock_screens.DAYS[weekday]} 31", valign="bottom")

    assert _band(frame, 8, 16) == _band(named, 8, 16)


@pytest.mark.parametrize(
    "screen,month,day,top,bottom",
    [
        (clock_screens.SCREEN_MAIN, 5, 31, "11:59 PM", "SUN 31"),
        (clock_screens.SCREEN_SEASON, 5, 31, "SPRING", "2026"),
        (clock_screens.SCREEN_TIME_SECONDS, 5, 31, "11:59:00", "PM"),
        (clock_screens.SCREEN_FULL_DATE, 5, 31, "MAY 31", "2026"),
        (clock_screens.SCREEN_FULL_DATE, 9, 23, "SEPT 23", "2026"),
        (clock_screens.SCREEN_BRAND, 5, 31, "KINHOLA", "M.COM"),
        (clock_screens.WAIT_ON, 5, 31, "GPS", "WAIT"),
    ],
)
def test_two_row_screens_show_the_expected_labels(
    screen: int, month: int, day: int, top: str, bottom: str
) -> None:
    frame = clock_screens.render_screen(screen, (2026, month, day, 6, 23, 59, 0))
    expected = Frame(32, 16)
    expected[0:8, 0:32] = Text(top)
    expected[8:16, 0:32] = Text(bottom, valign="bottom")

    assert same_frame(frame, expected)


@pytest.mark.parametrize(
    "screen,visible_fields",
    [
        (clock_screens.SCREEN_MAIN, {2, 3, 4, 5, 6}),
        (clock_screens.SCREEN_SEASON, {0, 1}),
        (clock_screens.SCREEN_TIME_SECONDS, {4, 5, 6}),
        (clock_screens.SCREEN_FULL_DATE, {0, 1, 2}),
        (clock_screens.SCREEN_CLOCK_MERIDIEM, {4, 5, 6}),
    ],
)
def test_content_keys_track_visible_rtc_fields_only(screen: int, visible_fields: set) -> None:
    original = clock_screens.render_screen(screen, _PARTS)
    original_key = clock_screens.screen_key(screen, _PARTS)
    replacements = (2027, 6, 30, 5, 11, 58, 59)

    for field, replacement in enumerate(replacements):
        parts = list(_PARTS)
        parts[field] = replacement
        frame = clock_screens.render_screen(screen, tuple(parts))
        changed = field in visible_fields
        assert (clock_screens.screen_key(screen, tuple(parts)) != original_key) is changed, field
        assert (not same_frame(frame, original)) is changed, field


def test_season_content_stays_cached_until_the_season_or_year_changes() -> None:
    march = (2026, 3, 1, 6, 0, 0, 0)
    may = (2026, 5, 31, 6, 23, 59, 59)

    assert clock_screens.screen_key(clock_screens.SCREEN_SEASON, march) == clock_screens.screen_key(
        clock_screens.SCREEN_SEASON, may
    )
    assert same_frame(
        clock_screens.render_screen(clock_screens.SCREEN_SEASON, march),
        clock_screens.render_screen(clock_screens.SCREEN_SEASON, may),
    )


def test_clock_meridiem_screen_fills_the_frame() -> None:
    """A short time scales up to fill the width next to a narrow meridiem badge."""
    parts = (2026, 6, 23, 1, 9, 5, 0)
    frame = clock_screens.render_screen(clock_screens.SCREEN_CLOCK_MERIDIEM, parts)
    unscaled_clock_width = Text("9:05", scale=(1, 1)).measure()[0]
    badge_width, badge_height = clock_screens._MeridiemBadge("AM").measure()
    left, right, top, bottom = lit_bounds(frame, 0, frame.height)

    assert left == 0
    assert right >= frame.width - 2
    # The seconds bar row stays blank at :00, so the lit height is the badge.
    assert (top, bottom) == (0, frame.height - 2)
    assert right - left + 1 > unscaled_clock_width + badge_width
    assert badge_width < Text("AM").measure()[0]
    assert bottom - top + 1 == badge_height


def test_clock_meridiem_screen_keeps_the_widest_time_in_bounds() -> None:
    parts = (2026, 6, 23, 1, 12, 59, 0)
    frame = clock_screens.render_screen(clock_screens.SCREEN_CLOCK_MERIDIEM, parts)
    left, right, top, bottom = lit_bounds(frame, 0, frame.height)

    assert left >= 0
    assert right <= frame.width - 1
    # Still horizontally centered; floor division leaves at most 1px of skew.
    assert 0 <= (frame.width - 1 - right) - left <= 1
    assert (top, bottom) == (0, frame.height - 2)


@pytest.mark.parametrize(
    "screen",
    [clock_screens.SCREEN_MAIN, clock_screens.SCREEN_CLOCK_MERIDIEM],
)
def test_seconds_free_faces_blink_the_colon_each_second(screen: int) -> None:
    colon_on = clock_screens.render_screen(screen, (2026, 6, 23, 1, 9, 5, 0))
    colon_off = clock_screens.render_screen(screen, (2026, 6, 23, 1, 9, 5, 1))

    assert not same_frame(colon_on, colon_off)
    assert lit_count(colon_on) > lit_count(colon_off)
    assert _band(colon_off, 0, 15) < _band(colon_on, 0, 15)


@pytest.mark.parametrize(
    "screen,row",
    [
        (clock_screens.SCREEN_MAIN, (clock_screens.HEIGHT_PIXELS // 2) - 1),
        (clock_screens.SCREEN_CLOCK_MERIDIEM, clock_screens.HEIGHT_PIXELS - 1),
    ],
)
def test_seconds_progress_bar_fills_across_the_minute(screen: int, row: int) -> None:
    def bar(second: int) -> int:
        return lit_row(clock_screens.render_screen(screen, (2026, 6, 23, 1, 12, 30, second)), row)

    assert bar(0) == 0
    assert bar(59) == clock_screens.WIDTH_PIXELS
    counts = [bar(second) for second in range(0, 60, 10)]
    assert counts == sorted(counts)


def test_frame_rate_screen_reports_the_measured_rate() -> None:
    frame = clock_screens.render_screen(clock_screens.SCREEN_FRAME_RATE, (7, 400, 175))
    label_only = Frame(32, 16)
    label_only[8:16, 0:32] = Text("FPS 17.5", valign="bottom")

    # The label band must contain exactly the rendered "FPS 17.5" glyphs.
    assert _band(frame, 8, 16) == _band(label_only, 8, 16)
    next_frame = clock_screens.render_screen(clock_screens.SCREEN_FRAME_RATE, (8, 450, 175))
    assert _band(frame, 0, 8) != _band(next_frame, 0, 8)
    assert _band(frame, 8, 16) == _band(next_frame, 8, 16)


@pytest.mark.parametrize(
    "fps_x10,expected",
    [
        (0, "0.0"),
        (175, "17.5"),
        (9_999, "999.9"),
        (12_345, "999.9"),  # clamped so the label never overflows the matrix
        (-5, "0.0"),
    ],
)
def test_frame_rate_label_is_clamped(fps_x10: int, expected: str) -> None:
    assert clock_screens._frame_rate_label(fps_x10) == expected


@pytest.mark.parametrize("parts", [None, (1, 2), (1, 2, 3, 4)])
def test_frame_rate_parts_rejects_malformed_input(parts: object) -> None:
    assert same_frame(
        clock_screens.render_screen(clock_screens.SCREEN_FRAME_RATE, parts),
        clock_screens.render_screen(clock_screens.SCREEN_FRAME_RATE, (0, 0, 0)),
    )


def test_uptime_screen_shows_dashes_before_the_first_fix() -> None:
    assert clock_screens._format_boot_date(None) == "--.--.--"
    # A None parts tuple collapses to the no-fix placeholder rather than raising.
    frame = clock_screens.render_screen(clock_screens.SCREEN_UPTIME, None)
    assert lit_count(frame) > 0


@pytest.mark.parametrize(
    "seconds,expected",
    [
        (0, "00:00:00"),
        (59, "00:00:59"),
        (3_600, "01:00:00"),
        (3_661, "01:01:01"),
        (86_399, "23:59:59"),
        (360_000, "100:00:00"),  # hours widen past two digits rather than wrap
    ],
)
def test_format_uptime_widens_hours_past_a_day(seconds: int, expected: str) -> None:
    assert clock_screens._format_uptime(seconds) == expected


@pytest.mark.parametrize(
    "boot,now,expected",
    [
        ((2026, 1, 31, 5, 23, 59, 30), (2026, 2, 1, 6, 0, 0, 30), 60),
        ((2025, 12, 31, 2, 23, 59, 30), (2026, 1, 1, 3, 0, 0, 30), 60),
        ((2024, 2, 28, 2, 0, 0, 0), (2024, 3, 1, 4, 0, 0, 0), 172_800),
        ((2000, 2, 28, 0, 0, 0, 0), (2000, 3, 1, 2, 0, 0, 0), 172_800),
        ((2100, 2, 28, 6, 0, 0, 0), (2100, 3, 1, 0, 0, 0, 0), 86_400),
    ],
)
def test_uptime_spans_calendar_boundaries(boot: tuple, now: tuple, expected: int) -> None:
    assert clock_screens._uptime_seconds(boot, now) == expected


def test_uptime_seconds_never_goes_negative() -> None:
    """A backwards RTC step (a later fix correcting the clock) must not wrap."""
    boot = (2026, 6, 23, 1, 12, 0, 0)
    now = (2026, 6, 23, 1, 11, 0, 0)

    assert clock_screens._uptime_seconds(boot, now) == 0


@pytest.mark.parametrize(
    "parts", [(None, (2026, 1, 1, 3, 0, 0, 0)), ((2026, 1, 1, 3, 0, 0, 0), None)]
)
def test_uptime_seconds_is_zero_without_both_endpoints(parts: tuple) -> None:
    assert clock_screens._uptime_seconds(*parts) == 0


def test_scroll_offset_holds_still_when_the_row_fits() -> None:
    assert clock_screens._scroll_offset(20, 32, 5_000) == 0


def test_scroll_offset_sweeps_out_and_back_as_a_triangle_wave() -> None:
    """An overflowing row eases to each edge and reverses, never jumping back."""
    overflow = 4
    text_width = 32 + overflow
    span_ms = 2 * overflow * clock_screens.SCROLL_MS_PER_PX
    offsets = [
        clock_screens._scroll_offset(text_width, 32, ms)
        for ms in range(0, span_ms, clock_screens.SCROLL_MS_PER_PX)
    ]

    assert offsets == [0, 1, 2, 3, 4, 3, 2, 1]
    # The wave repeats, so the marquee never drifts.
    assert clock_screens._scroll_offset(text_width, 32, span_ms) == 0


@pytest.mark.parametrize("scroll_ms,offset", [(0, 0), (99, 0), (100, 1), (300, 3)])
def test_uptime_scrolls_the_elapsed_time_and_latched_boot_date(scroll_ms: int, offset: int) -> None:
    boot = (2026, 1, 31, 5, 23, 59, 30)
    now = (2026, 2, 1, 6, 0, 0, 30)
    frame = clock_screens.render_screen(clock_screens.SCREEN_UPTIME, (boot, now, scroll_ms))

    for y0, label, valign in [(0, "UP 00:01:00", "middle"), (8, "BOOT: 31.01.26", "bottom")]:
        width = Text(label).measure()[0]
        strip = Frame(width, 8)
        strip[0:8, 0:width] = Text(label, align="left", valign=valign)
        expected = {
            (x, y + y0) for y in range(8) for x in range(32) if strip.value_at(x + offset, y)
        }
        assert _band(frame, y0, y0 + 8) == expected


def test_uptime_centers_both_rows_when_the_display_is_wide_enough() -> None:
    parts = (_PARTS, _PARTS, 5_000)
    frame = clock_screens.render_screen(clock_screens.SCREEN_UPTIME, parts, 64, 16)
    expected = Frame(64, 16)
    expected[0:8, 0:64] = Text("UP 00:00:00")
    expected[8:16, 0:64] = Text("BOOT: 31.05.26", valign="bottom")

    assert same_frame(frame, expected)


def test_uptime_key_updates_at_a_second_or_a_whole_pixel_of_scroll() -> None:
    screen = clock_screens.SCREEN_UPTIME
    key = clock_screens.screen_key(screen, (_PARTS, _PARTS, 0))

    assert clock_screens.screen_key(screen, (_PARTS, _PARTS, 99)) == key
    assert clock_screens.screen_key(screen, (_PARTS, _PARTS, 100)) != key
    assert clock_screens.screen_key(screen, (_PARTS, (*_PARTS[:6], 59), 0)) != key


@pytest.mark.parametrize("current", clock_screens.REGULAR_SCREENS)
def test_next_regular_can_choose_every_other_face_but_never_repeat(current: int) -> None:
    chosen = {clock_screens.choose_next_regular(current, FakeRandom([n])) for n in range(256)}

    assert chosen == set(clock_screens.REGULAR_SCREENS) - {current}


def test_next_regular_from_a_screen_outside_the_rotation_can_still_reach_them_all() -> None:
    """The cycle enters from an interstitial or the brand screen, not just a regular.

    `choose_next_regular` scans for its argument and silently keeps index 0 when
    it is absent, which would make the first regular screen unreachable. Nothing
    passes a non-regular today, so only this pins that the whole rotation stays
    available.
    """
    chosen = {
        clock_screens.choose_next_regular(clock_screens.SCREEN_BRAND, FakeRandom([n]))
        for n in range(256)
    }

    assert chosen == set(clock_screens.REGULAR_SCREENS)


def test_screen_choices_fall_back_to_the_module_random_source() -> None:
    """Every chooser defaults `rng=None` to `random`; the firmware relies on it.

    `clock_program` passes an rng explicitly, but the defaults are part of the
    published signature and nothing else executes that fallback.
    """
    for _ in range(32):
        assert clock_screens.choose_regular() in clock_screens.REGULAR_SCREENS
        assert clock_screens.choose_interstitial() in clock_screens.INTERSTITIAL_SCREENS
        current = clock_screens.REGULAR_SCREENS[0]
        assert clock_screens.choose_next_regular(current) in set(clock_screens.REGULAR_SCREENS) - {
            current
        }


def test_random_screen_selection_stays_within_each_kind_and_reaches_every_screen() -> None:
    assert {clock_screens.choose_regular(FakeRandom([n])) for n in range(256)} == {
        clock_screens.SCREEN_MAIN,
        clock_screens.SCREEN_CLOCK_MERIDIEM,
        clock_screens.SCREEN_TIME_SECONDS,
    }
    assert {clock_screens.choose_interstitial(FakeRandom([n])) for n in range(256)} == {
        clock_screens.SCREEN_SEASON,
        clock_screens.SCREEN_FULL_DATE,
        clock_screens.SCREEN_UPTIME,
    }


def _band(frame: object, y0: int, y1: int) -> set:
    """Return lit coordinates inside a row band."""
    return {(x, y) for y in range(y0, y1) for x in range(frame.width) if frame.value_at(x, y)}


def _parts_for(screen: int) -> tuple | None:
    """Return the render inputs each screen kind expects."""
    if clock_screens.is_wait(screen):
        return None
    if screen == clock_screens.SCREEN_UPTIME:
        return _PARTS, _PARTS, 0
    if screen == clock_screens.SCREEN_FRAME_RATE:
        return 7, 400, 175
    return _PARTS
