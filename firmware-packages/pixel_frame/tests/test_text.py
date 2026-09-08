"""Host CPython tests for text layout and the glyph table it draws from.

``Text`` measures and draws itself into a box it does not own, so the tests
assert rendered pixels rather than internal offsets. The glyph table gets its
own coverage here because nothing else has any: the clock's screen tests compare
``Text``-rendered output against ``Text``-rendered expectations, so a broken
letterform cancels out on both sides and passes.
"""

from __future__ import annotations

import pytest

from pixel_frame import Frame, Text
from pixel_frame.glyphs import _GLYPH_ROWS, HEIGHT, glyph


def test_measure_accounts_for_variable_glyph_widths_and_intercharacter_spacing() -> None:
    assert Text("M.i").measure() == (11, 7)
    assert Text("M.i", scale=(2, 3)).measure() == (22, 21)


@pytest.mark.parametrize("value", ["A", "a"])
def test_glyph_rows_render_in_visual_coordinates(value: str) -> None:
    frame = Frame(3, 7)

    frame[:, :] = Text(value)

    assert _rows(frame) == ["010", "101", "101", "111", "101", "101", "101"]


@pytest.mark.parametrize(
    "char,expected",
    [
        ("N", ("1001", "1101", "1011", "1001", "1001", "1001", "1001")),
        ("M", ("10001", "11011", "10101", "10001", "10001", "10001", "10001")),
        ("W", ("10001", "10001", "10001", "10001", "10101", "11011", "10001")),
    ],
)
def test_wide_glyphs_render_at_their_declared_width(char: str, expected: tuple[str, ...]) -> None:
    """N, M and W are the only glyphs wider than 3px, and nothing else draws them.

    A truncated row here silently narrows the glyph and shifts every following
    character in the label, which is invisible to any test that builds its
    expectation from ``Text`` as well.
    """
    width = len(expected[0])
    frame = Frame(width, HEIGHT)

    frame[:, :] = Text(char, scale=1, align="left", valign="top")

    assert glyph(char)[1] == width
    assert tuple(_rows(frame)) == expected


def test_every_declared_glyph_is_well_formed() -> None:
    """Structural invariants over the whole table, which nothing else touches."""
    for char, rows in _GLYPH_ROWS.items():
        cols, width = glyph(char)

        assert len(rows) == HEIGHT, char
        assert 1 <= width <= 5, char
        assert len(cols) == width, char
        assert all(set(row) <= {"0", "1"} for row in rows), char
        assert all(len(row) <= width for row in rows), char
        # Only the space is allowed to draw nothing at all.
        assert any(cols) is (char != " "), char


def test_unknown_characters_render_a_question_mark() -> None:
    frame = Frame(3, 7)

    frame[:, :] = Text("☃")

    assert _rows(frame) == ["111", "001", "001", "011", "010", "000", "010"]


@pytest.mark.parametrize(
    "align,x_offset,valign,y_offset",
    [("left", 0, "bottom", 4), ("center", 3, "top", 0), ("right", 6, "middle", 2)],
)
def test_alignment_respects_the_assigned_box_origin(
    align: str, x_offset: int, valign: str, y_offset: int
) -> None:
    frame = Frame(11, 15)

    frame[2:13, 3:10] = Text(":", scale=1, align=align, valign=valign)

    assert _lit_pixels(frame) == {(3 + x_offset, 4 + y_offset), (3 + x_offset, 6 + y_offset)}


@pytest.mark.parametrize(
    "width,height,scale,x0,y0",
    [(7, 22, 3, 2, 0), (2, 40, 2, 0, 13)],
)
def test_auto_scale_uses_largest_uniform_integer_that_fits(
    width: int, height: int, scale: int, x0: int, y0: int
) -> None:
    frame = Frame(width, height)
    text = Text(":")

    frame[:, :] = text

    assert text.measure(width, height) == (scale, 7 * scale)
    assert _lit_pixels(frame) == {
        (x0 + x, y0 + row * scale + y) for row in (2, 4) for y in range(scale) for x in range(scale)
    }


def test_explicit_anisotropic_scale_expands_each_source_pixel() -> None:
    frame = Frame(2, 21)

    frame[:, :] = Text(":", scale=(2, 3))

    assert _lit_pixels(frame) == {(x, y) for x in range(2) for y in (6, 7, 8, 12, 13, 14)}


def test_hidden_characters_reserve_layout_without_drawing() -> None:
    visible = Text(":.:", scale=1)
    hidden = Text(":.:", scale=1, hidden_chars=".")
    width, height = visible.measure()
    frame = Frame(width, height)

    frame[:, :] = hidden

    assert hidden.measure() == visible.measure()
    assert _lit_pixels(frame) == {(0, 2), (0, 4), (4, 2), (4, 4)}


@pytest.mark.parametrize("scale", [1, "auto"])
def test_overflow_draws_nothing_and_fits_reports_the_exact_boundary(scale: object) -> None:
    text = Text("12", scale=scale)
    frame = Frame(6, 7)
    frame.pixel(5, 6)

    frame[:, :] = text

    assert not text.fits(6, 7)
    assert not text.fits(7, 6)
    assert text.fits(7, 7)
    assert _lit_pixels(frame) == {(5, 6)}


@pytest.mark.parametrize("value,expected", [("", (0, 0)), (" ", (1, 7))])
def test_blank_text_preserves_existing_pixels(value: str, expected: tuple[int, int]) -> None:
    frame = Frame(3, 7)
    frame.pixel(0, 0)
    text = Text(value)

    frame[:, :] = text

    assert text.measure(3, 7) == expected
    assert text.fits(3, 7)
    assert _lit_pixels(frame) == {(0, 0)}


def test_non_string_values_render_as_their_decimal_text() -> None:
    """The clock passes ints and f-string numbers straight into Text."""
    frame = Frame(7, 7)

    frame[:, :] = Text(12, scale=1, align="left", valign="top")

    assert Text(12).measure() == Text("12").measure()
    assert _lit_pixels(frame) == _lit_pixels(_rendered("12", 7, 7))


@pytest.mark.parametrize("option", ["align", "valign"])
def test_invalid_layout_options_fail_at_construction(option: str) -> None:
    with pytest.raises(ValueError, match=option):
        Text("1", **{option: "invalid"})


@pytest.mark.parametrize("scale", [0, -1, (0, 1), (1, -1)])
def test_nonpositive_scales_are_rejected_when_layout_is_resolved(scale: object) -> None:
    with pytest.raises(ValueError, match="scale must be positive"):
        Text("1", scale=scale).measure()


def _rendered(value: str, width: int, height: int) -> Frame:
    """Return ``value`` drawn top-left into a fresh frame of the given size."""
    frame = Frame(width, height)
    frame[:, :] = Text(value, scale=1, align="left", valign="top")
    return frame


def _lit_pixels(frame: Frame) -> set[tuple[int, int]]:
    return {(x, y) for y in range(frame.height) for x in range(frame.width) if frame.value_at(x, y)}


def _rows(frame: Frame) -> list[str]:
    return [
        "".join("1" if frame.value_at(x, y) else "0" for x in range(frame.width))
        for y in range(frame.height)
    ]
