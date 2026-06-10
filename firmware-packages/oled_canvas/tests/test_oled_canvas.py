"""Host CPython pytest tests for the OledCanvas layout layer and BouncingText.

Exercises the geometry contract callers rely on: measurement arithmetic,
auto-fit scale selection, font blitting (including integer up-scaling and
clearing), centering, and the edge-reflecting sprite.
"""

from fake_driver import FakeDriver

from oled_canvas import BouncingText, OledCanvas

# '!' has only its centre column (index 2) set: byte 0x5F = rows 0,1,2,3,4,6.
_BANG_ROWS = (0, 1, 2, 3, 4, 6)


def test_text_width_includes_inter_glyph_gap(canvas):
    assert canvas.text_width("AB", 1) == 2 * 6
    assert canvas.text_width("AB", 2) == 2 * 6 * 2


def test_text_height_scales(canvas):
    assert canvas.text_height(1) == 8
    assert canvas.text_height(3) == 24


def test_fit_scale_picks_largest_fitting(canvas):
    # "8": width 6, height 8 → min(128//6, 64//8) = min(21, 8) = 8.
    assert canvas.fit_scale("8", 128, 64) == 8


def test_fit_scale_never_below_one(canvas):
    assert canvas.fit_scale("X" * 40, 128, 64) == 1  # 240px wide, can't fit


def test_fit_scale_empty_string(canvas):
    assert canvas.fit_scale("", 128, 64) == 1


def test_char_lights_expected_glyph_pixels(canvas, driver):
    canvas.char("!", 0, 0, 1)
    assert driver.lit == {(2, row) for row in _BANG_ROWS}


def test_char_scale_two_blocks_each_pixel(canvas, driver):
    canvas.char("!", 0, 0, 2)
    # Column 2 → x ∈ {4, 5}; each set row r → y ∈ {2r, 2r+1}.
    expected = {(x, y) for row in _BANG_ROWS for x in (4, 5) for y in (2 * row, 2 * row + 1)}
    assert driver.lit == expected


def test_char_outside_printable_range_is_blank(canvas, driver):
    canvas.char("\x01", 0, 0, 1)  # control char → blank glyph
    canvas.char(chr(0x90), 10, 0, 1)  # above 0x7E → blank glyph
    assert driver.lit == set()


def test_text_advances_per_character(canvas, driver):
    canvas.text("!!", 0, 0, 1)
    # First '!' centre column at x=2, second advances by 6 → x=8.
    assert (2, 0) in driver.lit
    assert (8, 0) in driver.lit


def test_text_centered_matches_explicit_origin():
    centered = OledCanvas(FakeDriver(128, 64), 128, 64)
    explicit = OledCanvas(FakeDriver(128, 64), 128, 64)
    centered.text_centered("A", 64, 32, 1)
    # width("A")=6, height=8 → top-left (64-3, 32-4).
    explicit.text("A", 61, 28, 1)
    assert centered.driver.lit == explicit.driver.lit
    assert centered.driver.lit  # non-empty


def test_color_zero_clears_pixels(canvas, driver):
    driver.fill(1)
    canvas.char("!", 0, 0, 1, color=0)
    assert (2, 0) not in driver.lit  # cleared by the glyph
    assert (0, 0) in driver.lit  # untouched column stays lit


def test_bouncing_text_auto_scales_to_fit(canvas):
    banner = BouncingText(canvas, "hi")  # scale=None
    assert banner.scale == canvas.fit_scale("hi", 128, 64)


def test_bouncing_text_reflects_off_edges(canvas):
    banner = BouncingText(canvas, "hi", scale=1, dx=200, dy=0)
    max_x = 128 - canvas.text_width("hi", 1)
    banner.step()
    assert banner.x == max_x
    assert banner.dx == -200
    banner.step()
    assert banner.x == 0
    assert banner.dx == 200


def test_bouncing_text_stays_in_bounds(canvas):
    banner = BouncingText(canvas, "hello", scale=2, dx=7, dy=5)
    max_x = 128 - canvas.text_width("hello", 2)
    max_y = 64 - canvas.text_height(2)
    for _ in range(200):
        banner.step()
        assert 0 <= banner.x <= max_x
        assert 0 <= banner.y <= max_y


def test_bouncing_text_max_scale_caps_auto_scale(canvas):
    # "1" auto-fits to scale 8 on 128x64; max_scale=3 should cap it.
    banner = BouncingText(canvas, "1", max_scale=3)
    assert banner.scale == 3


def test_bouncing_text_update_text_recomputes_bounds(canvas):
    banner = BouncingText(canvas, "1", scale=1)
    old_max_x = banner._max_x
    banner.update_text("hello world!")
    assert banner._max_x < old_max_x


def test_bouncing_text_update_text_clamps_position(canvas):
    banner = BouncingText(canvas, "1", scale=1)
    banner.x = banner._max_x  # push to far edge
    banner.update_text("hello world!")  # wider string → smaller max_x
    assert banner.x <= banner._max_x


def test_bouncing_text_random_reflect_stays_in_bounds(canvas):
    banner = BouncingText(canvas, "hi", scale=1, random_reflect=True)
    max_x = 128 - canvas.text_width("hi", 1)
    max_y = 64 - canvas.text_height(1)
    for _ in range(500):
        banner.step()
        assert 0 <= banner.x <= max_x
        assert 0 <= banner.y <= max_y


def test_bouncing_text_draw_renders(canvas, driver):
    banner = BouncingText(canvas, "hi", scale=1)
    banner.draw()
    assert driver.lit  # something was drawn
