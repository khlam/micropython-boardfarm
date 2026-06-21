"""Host CPython tests for the max7219 driver and font packing."""

from __future__ import annotations

import pytest
from fakes import FakeCS, FakeSPI

from max7219.max7219 import _FLIP_Y, _MIRROR_X, MAX7219, _text_columns

_NUM_CHIPS = 8
_PANEL_H = 8
_WIDTH = 32


def _make_display() -> tuple[MAX7219, FakeSPI, FakeCS]:
    spi, cs = FakeSPI(), FakeCS()
    return MAX7219(spi, cs), spi, cs


def _decode(writes: list[bytes]) -> set[tuple[int, int]]:
    """Reconstruct the lit visual pixels from refresh's SPI frames.

    Inverts ``refresh``'s mapping using the documented hardware model — chips
    emitted in reverse chain order, chips 0-3 the top panel and 4-7 the bottom,
    with the ``_MIRROR_X`` / ``_FLIP_Y`` orientation. Non-row register writes
    (init/intensity) are skipped.
    """
    lit: set[tuple[int, int]] = set()
    for frame in writes:
        reg = frame[0]
        if not 1 <= reg <= _PANEL_H:
            continue
        chip_row = reg - 1
        for pos in range(_NUM_CHIPS):
            data = frame[pos * 2 + 1]
            chip = _NUM_CHIPS - 1 - pos
            panel, col_chip = divmod(chip, 4)
            src_row = (_PANEL_H - 1 - chip_row) if _FLIP_Y else chip_row
            vy = panel * _PANEL_H + src_row
            for bit in range(8):
                if data & (1 << bit):
                    nat_x = col_chip * 8 + bit
                    vx = (_WIDTH - 1 - nat_x) if _MIRROR_X else nat_x
                    lit.add((vx, vy))
    return lit


# ---------------------------------------------------------------------------
# init / SPI framing
# ---------------------------------------------------------------------------


def test_init_writes_registers_and_toggles_cs() -> None:
    _, spi, cs = _make_display()
    # Init flashes the test register, sets 4 control regs, then clears 8 rows.
    assert len(spi.writes) > 0
    # Each SPI write is bracketed by exactly one CS off/on pair.
    assert cs.toggles.count("off") == cs.toggles.count("on") == len(spi.writes)


def test_refresh_writes_eight_frames() -> None:
    disp, spi, _ = _make_display()
    spi.writes.clear()
    disp.refresh()
    # One frame per chip-row; all eight chips ride in each frame.
    assert len(spi.writes) == _PANEL_H
    assert all(len(frame) == 2 * _NUM_CHIPS for frame in spi.writes)


def test_set_intensity_clamps_to_four_bits() -> None:
    disp, spi, _ = _make_display()
    spi.writes.clear()
    disp.set_intensity(0xFF)
    # One _write_all -> one SPI write of num_chips register/data pairs.
    assert len(spi.writes) == 1
    assert spi.writes[0][1] == 0x0F  # 0xFF & 0x0F


def test_dimensions_are_16x32() -> None:
    disp, _, _ = _make_display()
    assert (disp.width, disp.height) == (32, 16)


# ---------------------------------------------------------------------------
# framebuffer
# ---------------------------------------------------------------------------


def test_pixel_sets_and_clears_one_bit() -> None:
    disp, _, _ = _make_display()
    disp.pixel(0, 0)
    assert sum(b.bit_count() for b in disp._fb) == 1
    disp.pixel(0, 0, on=False)
    assert not any(disp._fb)


def test_pixel_out_of_range_is_noop() -> None:
    disp, _, _ = _make_display()
    for x, y in ((-1, 0), (32, 0), (0, -1), (0, 16)):
        disp.pixel(x, y)
    assert not any(disp._fb)


def test_pixel_accepts_full_16_row_height() -> None:
    disp, _, _ = _make_display()
    disp.pixel(0, 15)  # bottom panel is in range now
    assert any(disp._fb)


def test_fill_sets_then_clears_every_pixel() -> None:
    disp, _, _ = _make_display()
    disp.fill(on=True)
    assert all(b == 0xFF for b in disp._fb)
    disp.fill(on=False)
    assert not any(disp._fb)


def test_clear_zeros_framebuffer() -> None:
    disp, _, _ = _make_display()
    disp.draw_text("8", 0, 0)
    disp.clear()
    assert not any(disp._fb)


# ---------------------------------------------------------------------------
# geometry — refresh maps the framebuffer onto the chain correctly
# ---------------------------------------------------------------------------


def test_refresh_roundtrips_corner_pixels() -> None:
    disp, spi, _ = _make_display()
    corners = {(0, 0), (31, 0), (0, 15), (31, 15), (5, 9)}
    for x, y in corners:
        disp.pixel(x, y)
    spi.writes.clear()
    disp.refresh()
    assert _decode(spi.writes) == corners


def test_top_text_lands_on_top_panel_bottom_on_bottom() -> None:
    disp, spi, _ = _make_display()
    spi.writes.clear()
    disp.show_lines("TOP", "bot")
    lit = _decode(spi.writes)
    assert lit, "expected some pixels lit"
    # Each word stays inside its own 8-row panel band.
    tops = {(x, y) for x, y in lit if y < _PANEL_H}
    bots = {(x, y) for x, y in lit if y >= _PANEL_H}
    assert tops and bots
    assert all(0 <= y < _PANEL_H for _, y in tops)
    assert all(_PANEL_H <= y < 16 for _, y in bots)


# ---------------------------------------------------------------------------
# text rendering
# ---------------------------------------------------------------------------


def test_draw_text_lights_some_pixels() -> None:
    disp, _, _ = _make_display()
    disp.draw_text("8", 0, 0)
    assert any(disp._fb)


def test_show_lines_blank_renders_empty_framebuffer() -> None:
    disp, _, _ = _make_display()
    disp.show_lines(" ", " ")
    assert not any(disp._fb)


def test_draw_text_clips_overflow_without_error() -> None:
    disp, _, _ = _make_display()
    disp.draw_text("456 bottom", 0, 0)  # wider than 32px -> clips at right edge
    assert any(disp._fb)


def test_center_x_centers_narrow_and_clamps_wide() -> None:
    disp, _, _ = _make_display()
    # A narrow glyph is pushed in from the left edge to centre it.
    assert disp._center_x("T") == (_WIDTH - disp.text_width("T")) // 2 > 0
    # Text wider than the panel clamps to the left edge instead of going negative.
    assert disp._center_x("WIDE TEXT THAT OVERFLOWS") == 0


@pytest.mark.parametrize(
    "text,expected_width",
    [
        ("", 0),
        (" ", 2),  # blank glyph keeps a 2-col gap
        ("8", 5),  # full-width digit, no blank edges
    ],
)
def test_text_width(text: str, expected_width: int) -> None:
    disp, _, _ = _make_display()
    assert disp.text_width(text) == expected_width


def test_text_columns_inserts_gap_only_when_edges_collide() -> None:
    # "11": digit 1 is a single solid bar, so adjacent bars must be separated.
    _, two_ones = _text_columns("11")
    one_width = _text_columns("1")[1]
    assert two_ones == one_width * 2 + 1  # one separator column inserted
