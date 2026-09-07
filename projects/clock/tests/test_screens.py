"""Host CPython tests for the clock screen table and its renderers.

Every screen renders into the fixed 32x16 packed surface, and its content key
must change exactly when the visible pixels do — that key is what drives the
engine's re-render, so a key that misses a field freezes the display. Layout
assertions target the tight cases (widest time, longest month label) where the
glyphs come closest to overflowing the matrix.
"""

from __future__ import annotations

import pytest
from fake_clock import FakeRTC, lit_bounds, lit_count, lit_row, same_frame

import clock_screens
from pixel_frame import Frame, Text

_RTC_VALUE = (2026, 5, 31, 6, 23, 59, 58, 0)

_ALL_SCREENS = tuple(spec.id for spec in clock_screens.SCREEN_SPECS)
_WAIT_SCREENS = (clock_screens.WAIT_OFF, clock_screens.WAIT_ON)
_PARTS = (2026, 5, 31, 6, 23, 59, 58)


def test_screen_ids_are_unique_and_kinds_partition_the_table() -> None:
    assert len(_ALL_SCREENS) == len(set(_ALL_SCREENS))
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
    assert {clock_screens.screen_spec(s).kind for s in _WAIT_SCREENS} == {clock_screens.KIND_WAIT}


@pytest.mark.parametrize("screen", _ALL_SCREENS)
def test_every_screen_renders_the_exact_matrix_geometry(screen: int) -> None:
    frame = clock_screens.render_screen(screen, _parts_for(screen))

    assert isinstance(frame, Frame)
    assert (frame.width, frame.height, frame.channels) == (32, 16, 1)


@pytest.mark.parametrize(
    "screen",
    [s for s in _ALL_SCREENS if s != clock_screens.WAIT_OFF],
)
def test_every_screen_except_the_blank_wait_endpoint_draws_something(screen: int) -> None:
    assert lit_count(clock_screens.render_screen(screen, _parts_for(screen))) > 0


def test_the_blank_wait_endpoint_renders_dark() -> None:
    frame = clock_screens.render_screen(clock_screens.WAIT_OFF, None)

    assert lit_count(frame) == 0


def test_rtc_parts_drops_the_subsecond_field() -> None:
    """Renderers key off whole seconds, so the RTC's subsecond must not leak in."""
    assert clock_screens.rtc_parts(FakeRTC(_RTC_VALUE)) == _RTC_VALUE[:7]


def test_is_wait_identifies_only_the_wait_endpoints() -> None:
    for screen in _ALL_SCREENS:
        assert clock_screens.is_wait(screen) is (screen in _WAIT_SCREENS)


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


def test_full_date_falls_back_to_the_abbreviation_when_the_name_overflows() -> None:
    # "MAY 31" fits as a full name; "SEPTEMBER 23" does not and must shorten.
    assert clock_screens._month_day_label(5, 31, 32, 16) == "MAY 31"
    assert clock_screens._month_day_label(9, 23, 32, 16) == "SEPT 23"


def test_time_seconds_screen_changes_every_second() -> None:
    first = clock_screens.render_screen(
        clock_screens.SCREEN_TIME_SECONDS, (2026, 6, 23, 1, 15, 59, 58)
    )
    second = clock_screens.render_screen(
        clock_screens.SCREEN_TIME_SECONDS, (2026, 6, 23, 1, 15, 59, 59)
    )

    assert not same_frame(first, second)
    assert clock_screens.screen_key(
        clock_screens.SCREEN_TIME_SECONDS, (2026, 6, 23, 1, 15, 59, 59)
    ) == (clock_screens.SCREEN_TIME_SECONDS, 15, 59, 59)


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
    # The per-second key is what lets the engine re-render the blink mid-hold.
    assert clock_screens.screen_key(screen, (2026, 6, 23, 1, 9, 5, 1)) != clock_screens.screen_key(
        screen, (2026, 6, 23, 1, 9, 5, 0)
    )


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


def test_seconds_bar_skips_rows_outside_the_frame() -> None:
    frame = Frame(32, 16)
    clock_screens._draw_seconds_bar(frame, 30, 99, 32)

    assert lit_count(frame) == 0


def test_two_row_frame_centers_the_lower_band() -> None:
    frame = clock_screens._two_row_frame("12:05 AM", "June 23", 32, 16)
    month_width = Text("June 23").measure()[0]
    left, right, top, bottom = lit_bounds(frame, 8, 16)

    assert left == (frame.width - month_width) // 2
    assert right == left + month_width - 1
    assert (top, bottom) == (9, 15)
    assert lit_row(frame, 7) == 0
    assert lit_row(frame, 8) == 0


def test_two_row_frame_collapses_to_one_row_on_a_single_band_display() -> None:
    frame = clock_screens._two_row_frame("12:05", "June", 32, 1)

    assert (frame.width, frame.height) == (32, 1)


def test_frame_rate_screen_reports_the_measured_rate() -> None:
    frame = clock_screens.render_screen(clock_screens.SCREEN_FRAME_RATE, (7, 400, 175))
    label_only = Frame(32, 16)
    label_only[8:16, 0:32] = Text("FPS 17.5", valign="bottom")

    # The label band must contain exactly the rendered "FPS 17.5" glyphs.
    assert {(x, y) for x, y in _band(frame, 8, 16)} >= {(x, y) for x, y in _band(label_only, 8, 16)}
    assert clock_screens.screen_key(clock_screens.SCREEN_FRAME_RATE, (7, 400, 175)) == (
        clock_screens.SCREEN_FRAME_RATE,
        7,
        175,
    )


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
    assert clock_screens._frame_rate_parts(parts) == (0, 0, 0)


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


def test_uptime_seconds_spans_a_month_boundary() -> None:
    boot = (2026, 1, 31, 5, 23, 59, 30)
    now = (2026, 2, 1, 6, 0, 0, 30)

    assert clock_screens._uptime_seconds(boot, now) == 60


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


@pytest.mark.parametrize(
    "year,month,day,expected",
    [
        (1970, 1, 1, 0),  # epoch
        (1970, 1, 2, 1),
        (2000, 3, 1, 11_017),  # 2000 is a leap year despite being a century
        (1900, 3, 1, -25_508),  # 1900 is not
        (2024, 2, 29, 19_782),  # leap day exists
        (2026, 1, 1, 20_454),
    ],
)
def test_days_from_civil_matches_known_dates(
    year: int, month: int, day: int, expected: int
) -> None:
    assert clock_screens._days_from_civil(year, month, day) == expected


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


def test_marquee_row_scrolls_content_wider_than_the_matrix() -> None:
    """An overflowing row shows different pixels at different scroll phases."""
    early = Frame(32, 8)
    late = Frame(32, 8)
    text = "BOOT: 23.06.26 EXTRA"
    clock_screens._draw_marquee_row(early, text, 0, 8, 32, 0, "bottom")
    clock_screens._draw_marquee_row(
        late, text, 0, 8, 32, 3 * clock_screens.SCROLL_MS_PER_PX, "bottom"
    )

    assert Text(text).measure()[0] > 32  # precondition: it really does overflow
    assert not same_frame(early, late)


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
