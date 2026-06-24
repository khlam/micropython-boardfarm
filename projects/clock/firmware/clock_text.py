"""Compact packed text drawing helpers for the clock matrix."""

from pixel_display import Canvas

WIDTH_PIXELS = 32
HEIGHT_PIXELS = 16
ROW_HEIGHT = 8
COMPACT_GLYPH_HEIGHT = 7
COMPACT_GAP_PIXELS = 1
COMPACT_ON = 255
COMPACT_SCALE_1X = (1, 1)

_COMPACT_GLYPHS = {
    " ": (
        "0",
        "0",
        "0",
        "0",
        "0",
        "0",
        "0",
    ),
    ":": (
        "0",
        "0",
        "1",
        "0",
        "1",
        "0",
        "0",
    ),
    "0": (
        "111",
        "101",
        "101",
        "101",
        "101",
        "101",
        "111",
    ),
    "1": (
        "010",
        "110",
        "010",
        "010",
        "010",
        "010",
        "111",
    ),
    "2": (
        "111",
        "001",
        "001",
        "111",
        "100",
        "100",
        "111",
    ),
    "3": (
        "111",
        "001",
        "001",
        "111",
        "001",
        "001",
        "111",
    ),
    "4": (
        "101",
        "101",
        "101",
        "111",
        "001",
        "001",
        "001",
    ),
    "5": (
        "111",
        "100",
        "100",
        "111",
        "001",
        "001",
        "111",
    ),
    "6": (
        "111",
        "100",
        "100",
        "111",
        "101",
        "101",
        "111",
    ),
    "7": (
        "111",
        "001",
        "001",
        "010",
        "010",
        "010",
        "010",
    ),
    "8": (
        "111",
        "101",
        "101",
        "111",
        "101",
        "101",
        "111",
    ),
    "9": (
        "111",
        "101",
        "101",
        "111",
        "001",
        "001",
        "111",
    ),
    "A": (
        "010",
        "101",
        "101",
        "111",
        "101",
        "101",
        "101",
    ),
    "B": (
        "110",
        "101",
        "101",
        "110",
        "101",
        "101",
        "110",
    ),
    "C": (
        "111",
        "100",
        "100",
        "100",
        "100",
        "100",
        "111",
    ),
    "D": (
        "110",
        "101",
        "101",
        "101",
        "101",
        "101",
        "110",
    ),
    "E": (
        "111",
        "100",
        "100",
        "110",
        "100",
        "100",
        "111",
    ),
    "F": (
        "111",
        "100",
        "100",
        "110",
        "100",
        "100",
        "100",
    ),
    "G": (
        "111",
        "100",
        "100",
        "101",
        "101",
        "101",
        "111",
    ),
    "H": (
        "101",
        "101",
        "101",
        "111",
        "101",
        "101",
        "101",
    ),
    "I": (
        "111",
        "010",
        "010",
        "010",
        "010",
        "010",
        "111",
    ),
    "J": (
        "001",
        "001",
        "001",
        "001",
        "101",
        "101",
        "111",
    ),
    "L": (
        "100",
        "100",
        "100",
        "100",
        "100",
        "100",
        "111",
    ),
    "M": (
        "10001",
        "11011",
        "10101",
        "10001",
        "10001",
        "10001",
        "10001",
    ),
    "N": (
        "1001",
        "1101",
        "1011",
        "1001",
        "1001",
        "1001",
        "1001",
    ),
    "O": (
        "111",
        "101",
        "101",
        "101",
        "101",
        "101",
        "111",
    ),
    "P": (
        "110",
        "101",
        "101",
        "110",
        "100",
        "100",
        "100",
    ),
    "R": (
        "110",
        "101",
        "101",
        "110",
        "101",
        "101",
        "101",
    ),
    "S": (
        "111",
        "100",
        "100",
        "111",
        "001",
        "001",
        "111",
    ),
    "T": (
        "111",
        "010",
        "010",
        "010",
        "010",
        "010",
        "010",
    ),
    "U": (
        "101",
        "101",
        "101",
        "101",
        "101",
        "101",
        "111",
    ),
    "V": (
        "101",
        "101",
        "101",
        "101",
        "101",
        "101",
        "010",
    ),
    "W": (
        "10001",
        "10001",
        "10001",
        "10001",
        "10101",
        "11011",
        "10001",
    ),
    "Y": (
        "101",
        "101",
        "101",
        "010",
        "010",
        "010",
        "010",
    ),
}


def compact_glyph(char: str) -> tuple:
    """Return a compact display glyph, using a blank cell for unknown text."""
    return _COMPACT_GLYPHS.get(char.upper(), _COMPACT_GLYPHS[" "])


def compact_text_width(
    text: str,
    gap_pixels: int = COMPACT_GAP_PIXELS,
    x_scale: int = 1,
) -> int:
    """Return the compact display glyph width for ``text``."""
    width = 0
    for char in text:
        if width:
            width += gap_pixels
        pattern = compact_glyph(char)
        width += len(pattern[0]) * x_scale
    return width


def draw_compact_glyph(
    canvas: object,
    pattern: tuple,
    x0: int,
    y0: int,
    *,
    intensity: int = COMPACT_ON,
    x_scale: int = 1,
    y_scale: int = 1,
) -> None:
    """Draw one compact display glyph into ``canvas``."""
    if intensity <= 0:
        return
    for y, row in enumerate(pattern):
        dy = y0 + (y * y_scale)
        for x, bit in enumerate(row):
            if bit == "1":
                dx = x0 + (x * x_scale)
                for sy in range(y_scale):
                    for sx in range(x_scale):
                        canvas.pixel(dx + sx, dy + sy)


def draw_compact_text_at(
    canvas: object,
    text: str,
    x0: int,
    y0: int,
    *,
    gap_pixels: int = COMPACT_GAP_PIXELS,
    colon_visible: bool = True,
    intensity: int = COMPACT_ON,
    scale: tuple = COMPACT_SCALE_1X,
) -> None:
    """Draw compact text at an exact origin."""
    x_scale, y_scale = scale
    for char in text:
        pattern = compact_glyph(char)
        if char != ":" or colon_visible:
            draw_compact_glyph(
                canvas,
                pattern,
                x0,
                y0,
                intensity=intensity,
                x_scale=x_scale,
                y_scale=y_scale,
            )
        x0 += (len(pattern[0]) * x_scale) + gap_pixels


def draw_compact_text_in_box(
    canvas: object,
    text: str,
    box: tuple,
    *,
    gap_pixels: int = COMPACT_GAP_PIXELS,
    y_offset: int = 0,
    colon_visible: bool = True,
) -> None:
    """Draw compact text centered in a clipped rectangular display area."""
    x0, y0, width, height = box
    text_width = compact_text_width(text, gap_pixels)
    tx = x0 + (width - text_width) // 2
    ty = y0 + (height - COMPACT_GLYPH_HEIGHT) // 2 + y_offset
    draw_compact_text_at(
        canvas,
        text,
        tx,
        ty,
        gap_pixels=gap_pixels,
        colon_visible=colon_visible,
    )


def two_row_frame(
    top: str,
    bottom: str,
    *,
    top_y_offset: int = 0,
    bottom_y_offset: int = 1,
    top_colon_visible: bool = True,
) -> object:
    """Render two compact rows into a full display-sized packed frame."""
    canvas = Canvas(WIDTH_PIXELS, HEIGHT_PIXELS, COMPACT_ON)
    draw_compact_text_in_box(
        canvas,
        top,
        (0, 0, WIDTH_PIXELS, ROW_HEIGHT),
        y_offset=top_y_offset,
        colon_visible=top_colon_visible,
    )
    draw_compact_text_in_box(
        canvas,
        bottom,
        (0, ROW_HEIGHT, WIDTH_PIXELS, ROW_HEIGHT),
        y_offset=bottom_y_offset,
    )
    return canvas.frame()


def blank_frame() -> object:
    """Return a blank full display-sized packed frame."""
    return Canvas(WIDTH_PIXELS, HEIGHT_PIXELS, 0).frame()
