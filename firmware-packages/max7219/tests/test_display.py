"""Host CPython tests for the max7219 driver and font packing."""

from __future__ import annotations

import pytest
from fakes import FakeCS, FakeSPI

from max7219.max7219 import MAX7219, _text_columns


def _make_display() -> tuple[MAX7219, FakeSPI, FakeCS]:
    spi, cs = FakeSPI(), FakeCS()
    return MAX7219(spi, cs), spi, cs


# ---------------------------------------------------------------------------
# init / SPI framing
# ---------------------------------------------------------------------------


def test_init_writes_registers_and_toggles_cs() -> None:
    _, spi, cs = _make_display()
    # Init flashes the test register, sets 4 control regs, then clears 8 rows.
    assert len(spi.writes) > 0
    # Each SPI write is bracketed by exactly one CS off/on pair.
    assert cs.toggles.count("off") == cs.toggles.count("on") == len(spi.writes)


def test_refresh_writes_eight_rows() -> None:
    disp, spi, _ = _make_display()
    spi.writes.clear()
    disp.refresh()
    assert len(spi.writes) == 8


def test_set_intensity_clamps_to_four_bits() -> None:
    disp, spi, _ = _make_display()
    spi.writes.clear()
    disp.set_intensity(0xFF)
    # One _write_all -> one SPI write of num_modules register/data pairs.
    assert len(spi.writes) == 1
    # Low nibble of every data byte is 0x0F (0xFF & 0x0F).
    assert spi.writes[0][1] == 0x0F


def test_width_matches_module_count() -> None:
    disp, _, _ = _make_display()
    assert disp.width == 32


# ---------------------------------------------------------------------------
# framebuffer
# ---------------------------------------------------------------------------


def test_clear_zeros_framebuffer() -> None:
    disp, _, _ = _make_display()
    disp.show_text("8")
    disp.clear()
    assert not any(disp._buf)


def test_pixel_sets_and_clears_one_bit() -> None:
    disp, _, _ = _make_display()
    # Top-left pixel maps to the mirrored far end of the chain.
    disp.pixel(0, 0)
    assert sum(b.bit_count() for b in disp._buf) == 1
    disp.pixel(0, 0, on=False)
    assert not any(disp._buf)


def test_pixel_out_of_range_is_noop() -> None:
    disp, _, _ = _make_display()
    disp.pixel(-1, 0)
    disp.pixel(0, 8)
    disp.pixel(32, 0)
    assert not any(disp._buf)


def test_fill_sets_then_clears_every_pixel() -> None:
    disp, _, _ = _make_display()
    disp.fill(on=True)
    assert all(b == 0xFF for b in disp._buf)
    disp.fill(on=False)
    assert not any(disp._buf)


# ---------------------------------------------------------------------------
# text rendering
# ---------------------------------------------------------------------------


def test_show_text_lights_some_pixels() -> None:
    disp, _, _ = _make_display()
    disp.show_text("8")
    assert any(disp._buf)


def test_blank_text_renders_empty_framebuffer() -> None:
    disp, _, _ = _make_display()
    disp.show_text(" ")
    assert not any(disp._buf)


def test_show_text_wider_than_display_clips_without_error() -> None:
    disp, _, _ = _make_display()
    disp.show_text("456 bot")  # overflows 32px -> left-aligned, right edge clips
    assert any(disp._buf)


@pytest.mark.parametrize(
    "text,expected_width",
    [
        ("", 0),
        (" ", 2),  # blank glyph keeps a 2-col gap
        ("8", 5),  # full-width digit, no blank edges
    ],
)
def test_text_columns_width(text: str, expected_width: int) -> None:
    _, width = _text_columns(text)
    assert width == expected_width


def test_text_columns_inserts_gap_only_when_edges_collide() -> None:
    # "11": digit 1 is a single solid bar, so adjacent bars must be separated.
    _, two_ones = _text_columns("11")
    one_width = _text_columns("1")[1]
    assert two_ones == one_width * 2 + 1  # one separator column inserted
