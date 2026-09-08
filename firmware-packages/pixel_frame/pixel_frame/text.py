"""Declarative text content for packed pixel frames."""

from pixel_frame.glyphs import HEIGHT, SPACING, glyph

_ALIGN_LEFT = "left"
_ALIGN_CENTER = "center"
_ALIGN_RIGHT = "right"
_VALIGN_TOP = "top"
_VALIGN_MIDDLE = "middle"
_VALIGN_BOTTOM = "bottom"


class Text:
    """Text that can measure and draw itself inside a frame box."""

    def __init__(
        self,
        value: object,
        *,
        scale: tuple | None = None,
        align: str = _ALIGN_CENTER,
        valign: str = _VALIGN_MIDDLE,
        hidden_chars: str = "",
    ) -> None:
        """Store text layout intent without binding it to a frame.

        ``scale`` is an explicit ``(x, y)`` integer pair, or ``None`` to grow to
        the largest uniform scale that fits the box the text is assigned into.
        """
        if align not in (_ALIGN_LEFT, _ALIGN_CENTER, _ALIGN_RIGHT):
            raise ValueError("align must be 'left', 'center', or 'right'")
        if valign not in (_VALIGN_TOP, _VALIGN_MIDDLE, _VALIGN_BOTTOM):
            raise ValueError("valign must be 'top', 'middle', or 'bottom'")
        self.value = str(value)
        self.scale = scale
        self.align = align
        self.valign = valign
        self.hidden_chars = hidden_chars

    def measure(self, box_width: int | None = None, box_height: int | None = None) -> tuple:
        """Return rendered width and height for the configured text."""
        x_scale, y_scale = self._scale_for_box(box_width, box_height)
        return self._measure_at_scale(x_scale, y_scale)

    def fits(self, width: int, height: int) -> bool:
        """Return whether this text can render inside a pixel box.

        Use this before assigning into a frame box when firmware wants to pick
        shorter alternate text instead of letting an overlong label draw blank.
        """
        text_width, text_height = self.measure(width, height)
        return text_width <= width and text_height <= height

    def draw(self, frame: object, x0: int, y0: int, width: int, height: int) -> None:
        """Draw the text into an assigned pixel box."""
        x_scale, y_scale = self._scale_for_box(width, height)
        text_width, text_height = self._measure_at_scale(x_scale, y_scale)
        if text_width <= 0 or text_height <= 0:
            return
        if text_width > width or text_height > height:
            return
        x = x0 + _aligned_offset(width, text_width, self.align)
        ty = y0 + _aligned_offset(height, text_height, self.valign)
        # Advance exactly as _measure_at_scale does, so layout and drawing agree.
        for i, char in enumerate(self.value):
            cols, glyph_width = glyph(char)
            if i:
                x += SPACING * x_scale
            if char not in self.hidden_chars:
                _draw_glyph(frame, cols, glyph_width, x, ty, x_scale, y_scale)
            x += glyph_width * x_scale

    def _scale_for_box(self, box_width: int | None, box_height: int | None) -> tuple:
        """Return explicit or largest fitting integer scale."""
        if self.scale is not None:
            return _positive_scale(self.scale[0]), _positive_scale(self.scale[1])
        if box_width is None or box_height is None:
            return 1, 1
        base_width, base_height = self._measure_at_scale(1, 1)
        if base_width <= 0 or base_height <= 0:
            return 1, 1
        scale = max(1, min(box_width // base_width, box_height // base_height))
        return scale, scale

    def _measure_at_scale(self, x_scale: int, y_scale: int) -> tuple:
        """Return text bounds at one explicit scale."""
        if not self.value:
            return 0, 0
        width = (len(self.value) - 1) * SPACING
        for char in self.value:
            _cols, glyph_width = glyph(char)
            width += glyph_width
        return width * x_scale, HEIGHT * y_scale


def _draw_glyph(
    frame: object,
    cols: bytes,
    width: int,
    x0: int,
    y0: int,
    x_scale: int,
    y_scale: int,
) -> None:
    """Draw one scaled glyph into a packed frame."""
    for x in range(width):
        bits = cols[x]
        if bits == 0:
            continue
        dx = x0 + (x * x_scale)
        for y in range(HEIGHT):
            if bits & (1 << y):
                dy = y0 + (y * y_scale)
                _draw_scaled_pixel(frame, dx, dy, x_scale, y_scale)


def _draw_scaled_pixel(
    frame: object,
    x0: int,
    y0: int,
    x_scale: int,
    y_scale: int,
) -> None:
    """Draw one scaled source pixel into a packed frame."""
    for sy in range(y_scale):
        y = y0 + sy
        for sx in range(x_scale):
            frame.set_pixel_unchecked(x0 + sx, y)


def _aligned_offset(box_size: int, content_size: int, alignment: str) -> int:
    """Return one-axis alignment offset."""
    if alignment in (_ALIGN_LEFT, _VALIGN_TOP):
        return 0
    if alignment in (_ALIGN_RIGHT, _VALIGN_BOTTOM):
        return box_size - content_size
    return (box_size - content_size) // 2


def _positive_scale(value: object) -> int:
    """Return a positive integer scale."""
    scale = int(value)
    if scale <= 0:
        raise ValueError("scale must be positive")
    return scale
