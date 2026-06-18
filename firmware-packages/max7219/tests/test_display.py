"""Host CPython tests for the max7219 driver, fonts, and display cycle."""

from __future__ import annotations

import pytest
import utime
from fakes import FakeCS, FakeDisplay, FakeRTC, FakeSPI

from max7219 import DisplayCycle, day_name, format_time_12h
from max7219.max7219 import MAX7219

# ---------------------------------------------------------------------------
# format_time_12h
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "hour24,minute,colon_on,expected",
    [
        (0, 0, True, ("12:00", "AM")),  # midnight
        (0, 5, False, ("12 05", "AM")),  # colon off -> space
        (9, 7, True, ("9:07", "AM")),
        (11, 59, True, ("11:59", "AM")),
        (12, 0, True, ("12:00", "PM")),  # noon
        (12, 30, False, ("12 30", "PM")),
        (13, 5, True, ("1:05", "PM")),
        (23, 59, True, ("11:59", "PM")),
    ],
)
def test_format_time_12h(hour24: int, minute: int, colon_on: bool, expected: tuple) -> None:  # noqa: FBT001
    assert format_time_12h(hour24, minute, colon_on=colon_on) == expected


# ---------------------------------------------------------------------------
# day_name
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "wd,expected",
    [
        (0, "MONDAY"),
        (2, "WEDNESDAY"),
        (6, "SUNDAY"),
        (-1, "?"),
        (7, "?"),
    ],
)
def test_day_name(wd: int, expected: str) -> None:
    assert day_name(wd) == expected


# ---------------------------------------------------------------------------
# MAX7219 driver / framebuffer
# ---------------------------------------------------------------------------


def _make_display() -> tuple[MAX7219, FakeSPI, FakeCS]:
    spi, cs = FakeSPI(), FakeCS()
    return MAX7219(spi, cs), spi, cs


def test_init_writes_registers_and_toggles_cs() -> None:
    _, spi, cs = _make_display()
    # Init flashes the test register, sets 4 control regs, clears 8 rows.
    assert len(spi.writes) > 0
    # Each SPI write is bracketed by a CS off/on pair.
    assert cs.toggles.count("off") == cs.toggles.count("on") == len(spi.writes)


def test_clear_zeros_framebuffer() -> None:
    disp, _, _ = _make_display()
    disp.show_text("8")
    disp.clear()
    assert not any(disp._buf)


def test_blank_text_renders_empty_framebuffer() -> None:
    disp, _, _ = _make_display()
    disp.show_text(" ")
    assert not any(disp._buf)


def test_show_text_lights_some_pixels() -> None:
    disp, _, _ = _make_display()
    disp.show_text("8")
    assert any(disp._buf)


def test_refresh_writes_eight_rows() -> None:
    disp, spi, _ = _make_display()
    spi.writes.clear()
    disp.refresh()
    assert len(spi.writes) == 8


def test_set_intensity_clamps_to_four_bits() -> None:
    disp, spi, _ = _make_display()
    spi.writes.clear()
    disp.set_intensity(0xFF)
    # One _write_all -> one SPI write of NUM_MODULES register/data pairs.
    assert len(spi.writes) == 1
    # Low nibble of every data byte is 0x0F (0xFF & 0x0F).
    assert spi.writes[0][1] == 0x0F


@pytest.mark.parametrize(
    "text,expected_width",
    [
        ("", 0),
        (" ", 2),  # blank glyph keeps a 2-col gap
        ("8", 5),  # full-width digit, no blank edges
    ],
)
def test_build_cols_width(text: str, expected_width: int) -> None:
    disp, _, _ = _make_display()
    _, width = disp._build_cols(text)
    assert width == expected_width


def test_show_time_lights_both_regions() -> None:
    disp, _, _ = _make_display()
    from max7219.font_bold import char_cols, char_cols_tiny

    disp.show_time("1:05", "PM", char_cols, char_cols_tiny)
    assert any(disp._buf)


def test_scroll_step_advances_and_wraps() -> None:
    disp, _, _ = _make_display()
    disp.set_text("HELLO")
    assert disp._scroll_pos == 0
    disp.scroll_step()
    assert disp._scroll_pos == 1


def test_show_auto_long_text_sets_wiggle() -> None:
    disp, _, _ = _make_display()
    disp.show_auto("WEDNESDAY")  # 9 chars overflow 32px
    assert disp._wiggle_max > 0
    before = disp._scroll_pos
    disp.wiggle_step()
    assert disp._scroll_pos != before


def test_show_auto_short_text_centers_without_animation() -> None:
    disp, _, _ = _make_display()
    disp.show_auto("8")  # fits in 32px
    assert disp._text_buf is None
    assert any(disp._buf)


def test_set_text_wiggle_loads_overflowing_buffer() -> None:
    disp, _, _ = _make_display()
    disp.set_text_wiggle("WEDNESDAY")
    assert disp._text_buf is not None
    assert disp._wiggle_max > 0


def test_scroll_step_is_noop_without_text() -> None:
    disp, _, _ = _make_display()  # _text_buf is None after init
    disp.scroll_step()
    assert disp._scroll_pos == 0


def test_scroll_step_wraps_at_end() -> None:
    disp, _, _ = _make_display()
    disp.set_text("HI")
    disp._scroll_pos = disp._text_len - 32  # at the last visible window
    disp.scroll_step()
    assert disp._scroll_pos == 0


def test_wiggle_step_is_noop_without_text() -> None:
    disp, _, _ = _make_display()
    disp.wiggle_step()
    assert disp._scroll_pos == 0


def test_wiggle_step_reverses_at_both_edges() -> None:
    disp, _, _ = _make_display()
    disp.show_auto("WEDNESDAY")
    # At the right edge, direction flips to -1.
    disp._scroll_pos = disp._wiggle_max
    disp._wiggle_dir = 1
    disp.wiggle_step()
    assert disp._scroll_pos == disp._wiggle_max
    assert disp._wiggle_dir == -1
    # At the left edge, direction flips back to +1.
    disp._scroll_pos = 0
    disp._wiggle_dir = -1
    disp.wiggle_step()
    assert disp._scroll_pos == 0
    assert disp._wiggle_dir == 1


def test_show_text_wider_than_display_clamps_offset() -> None:
    disp, _, _ = _make_display()
    disp.show_text("WEDNESDAY")  # wider than 32px -> offset clamped to 0
    assert any(disp._buf)


# ---------------------------------------------------------------------------
# DisplayCycle  (utime.ticks_ms monkeypatched for deterministic phases)
# ---------------------------------------------------------------------------


def test_cycle_time_then_day_then_back(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = {"t": 0}
    monkeypatch.setattr(utime, "ticks_ms", lambda: clock["t"])

    disp = FakeDisplay()
    # 13:05 on a Wednesday (weekday index 2).
    rtc = FakeRTC((2025, 6, 18, 2, 13, 5, 0, 0))
    cycle = DisplayCycle(disp, rtc)
    cycle.start()
    assert disp.calls[-1] == ("show_time", "1:05", "PM")

    # +1s: colon blinks off (separator becomes a space).
    clock["t"] = 1000
    cycle.step()
    assert disp.calls[-1] == ("show_time", "1 05", "PM")

    # +5s: TIME window elapsed -> DAY phase shows the weekday name.
    clock["t"] = 5000
    cycle.step()
    assert disp.calls[-1] == ("show_auto", "WEDNESDAY")

    # During DAY: the wiggle advances the overflowing name.
    clock["t"] = 5120
    cycle.step()
    assert ("wiggle_step",) in disp.calls

    # +3s in DAY -> back to TIME.
    clock["t"] = 8000
    cycle.step()
    assert disp.calls[-1] == ("show_time", "1:05", "PM")
