"""Declarative text content for packed pixel frames."""

from pixel_frame.glyphs import HEIGHT, SPACING, glyph

_ALIGN_LEFT = "left"
_ALIGN_CENTER = "center"
_ALIGN_RIGHT = "right"
_VALIGN_TOP = "top"
_VALIGN_MIDDLE = "middle"
_VALIGN_BOTTOM = "bottom"
_FLOW_HORIZONTAL = "horizontal"
_FLOW_VERTICAL = "vertical"
_SCALE_AUTO = "auto"


class Text:
    """Text that can measure and draw itself inside a frame box."""

    def __init__(
        self,
        value: object,
        *,
        scale: object = _SCALE_AUTO,
        align: str = _ALIGN_CENTER,
        valign: str = _VALIGN_MIDDLE,
        flow: str = _FLOW_HORIZONTAL,
        hidden_chars: str = "",
    ) -> None:
        """Store text layout intent without binding it to a frame."""
        if align not in (_ALIGN_LEFT, _ALIGN_CENTER, _ALIGN_RIGHT):
            raise ValueError("align must be 'left', 'center', or 'right'")
        if valign not in (_VALIGN_TOP, _VALIGN_MIDDLE, _VALIGN_BOTTOM):
            raise ValueError("valign must be 'top', 'middle', or 'bottom'")
        if flow not in (_FLOW_HORIZONTAL, _FLOW_VERTICAL):
            raise ValueError("flow must be 'horizontal' or 'vertical'")
        self.value = str(value)
        self.scale = scale
        self.align = align
        self.valign = valign
        self.flow = flow
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
        tx = x0 + _aligned_offset(width, text_width, self.align)
        ty = y0 + _aligned_offset(height, text_height, self.valign)
        if self.flow == _FLOW_VERTICAL:
            self._draw_vertical(frame, tx, ty, x_scale, y_scale)
            return
        self._draw_horizontal(frame, tx, ty, x_scale, y_scale)

    def _draw_horizontal(
        self,
        frame: object,
        x0: int,
        y0: int,
        x_scale: int,
        y_scale: int,
    ) -> None:
        """Draw horizontal text at the resolved origin."""
        x = x0
        last = len(self.value) - 1
        for i, char in enumerate(self.value):
            cols, width = glyph(char)
            if char not in self.hidden_chars:
                _draw_glyph(frame, cols, width, x, y0, x_scale, y_scale)
            x += width * x_scale
            if i != last:
                x += SPACING * x_scale

    def _draw_vertical(
        self,
        frame: object,
        x0: int,
        y0: int,
        x_scale: int,
        y_scale: int,
    ) -> None:
        """Draw vertical text at the resolved origin."""
        y = y0
        last = len(self.value) - 1
        for i, char in enumerate(self.value):
            cols, width = glyph(char)
            if char not in self.hidden_chars:
                _draw_glyph(frame, cols, width, x0, y, x_scale, y_scale)
            y += HEIGHT * y_scale
            if i != last:
                y += SPACING * y_scale

    def _scale_for_box(self, box_width: int | None, box_height: int | None) -> tuple:
        """Return explicit or largest fitting integer scale."""
        if self.scale == _SCALE_AUTO:
            if box_width is None or box_height is None:
                return 1, 1
            return self._auto_scale(box_width, box_height)
        if isinstance(self.scale, tuple):
            return _positive_scale(self.scale[0]), _positive_scale(self.scale[1])
        scale = _positive_scale(self.scale)
        return scale, scale

    def _auto_scale(self, box_width: int, box_height: int) -> tuple:
        """Return the largest uniform scale that fits the box."""
        base_width, base_height = self._measure_at_scale(1, 1)
        if base_width <= 0 or base_height <= 0:
            return 1, 1
        scale = min(box_width // base_width, box_height // base_height)
        if scale <= 0:
            return 1, 1
        return scale, scale

    def _measure_at_scale(self, x_scale: int, y_scale: int) -> tuple:
        """Return text bounds at one explicit scale."""
        if not self.value:
            return 0, 0
        if self.flow == _FLOW_VERTICAL:
            width = 0
            for char in self.value:
                _cols, glyph_width = glyph(char)
                width = max(width, glyph_width * x_scale)
            height = (len(self.value) * HEIGHT * y_scale) + (
                (len(self.value) - 1) * SPACING * y_scale
            )
            return width, height
        width = 0
        for i, char in enumerate(self.value):
            _cols, glyph_width = glyph(char)
            if i:
                width += SPACING * x_scale
            width += glyph_width * x_scale
        return width, HEIGHT * y_scale


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
