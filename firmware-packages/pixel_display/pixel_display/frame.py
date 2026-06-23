"""Compact frame objects and text constructors for pixel displays."""

from pixel_display import font5x7

_CHANNELS_INTENSITY = 1
_LINE_HEIGHT = 8


class Frame:
    """Row-major n-channel pixel matrix backed by a compact byte buffer."""

    def __init__(self, width: int, height: int, channels: int, data: bytearray) -> None:
        """Store frame geometry and pixel bytes.

        Args:
            width: Frame width in pixels.
            height: Frame height in pixels.
            channels: Number of byte channels per pixel.
            data: Row-major bytes, ``height * width * channels`` long.

        Raises:
            ValueError: If geometry is not positive or data length mismatches it.
        """
        if width <= 0 or height <= 0 or channels <= 0:
            raise ValueError("frame geometry must be positive")
        expected = width * height * channels
        if len(data) != expected:
            raise ValueError("frame data length does not match geometry")
        self.width = width
        self.height = height
        self.channels = channels
        self.data = data

    @classmethod
    def blank(cls, width: int, height: int, channels: int = _CHANNELS_INTENSITY) -> "Frame":
        """Create an all-off frame."""
        return cls(width, height, channels, bytearray(width * height * channels))

    @classmethod
    def from_matrix(cls, matrix: list) -> "Frame":
        """Create a frame from a 2D intensity or 3D channel matrix.

        Args:
            matrix: Rows of pixels. A pixel may be a normalized scalar or a
                sequence of normalized channel values.

        Returns:
            A frame with values quantized to bytes.

        """
        width, height, channels, data = _matrix_geometry_and_data(matrix)
        return cls(width, height, channels, data)

    @classmethod
    def text(cls, text: object, intensity: float = 1.0) -> "Frame":
        """Render text into a compact one-channel frame."""
        columns, width = _text_columns(str(text))
        if width <= 0:
            return cls.blank(1, font5x7.HEIGHT)
        data = bytearray(width * font5x7.HEIGHT)
        value = _quantize(intensity)
        for x in range(width):
            bits = columns[x]
            if bits == 0:
                continue
            for y in range(font5x7.HEIGHT):
                if bits & (1 << y):
                    data[y * width + x] = value
        return cls(width, font5x7.HEIGHT, _CHANNELS_INTENSITY, data)

    @classmethod
    def number(cls, value: object, intensity: float = 1.0) -> "Frame":
        """Render a number-like value using the text renderer."""
        return cls.text(str(value), intensity)

    @classmethod
    def text_lines(cls, lines: tuple, intensity: float = 1.0) -> "Frame":
        """Render one or more text rows into a compact one-channel frame."""
        rendered = []
        width = 1
        for line in lines:
            columns, line_width = _text_columns(str(line))
            rendered.append((columns, line_width))
            width = max(width, line_width)
        if not rendered:
            return cls.blank(1, 1)
        height = len(rendered) * _LINE_HEIGHT
        data = bytearray(width * height)
        value = _quantize(intensity)
        for line_index, item in enumerate(rendered):
            columns, line_width = item
            _draw_columns(data, width, line_index, columns, line_width, value)
        return cls(width, height, _CHANNELS_INTENSITY, data)

    def value_at(self, x: int, y: int, channel: int = 0) -> int:
        """Return one byte value from the frame."""
        return self.data[(y * self.width + x) * self.channels + channel]


def _pixel_channels(pixel: object) -> tuple:
    """Return a tuple of scalar channel values for one matrix pixel."""
    if isinstance(pixel, (list, tuple, bytearray)):
        if len(pixel) <= 0:
            raise ValueError("matrix channel pixels must not be empty")
        return tuple(pixel)
    return (pixel,)


def _matrix_geometry_and_data(matrix: list) -> tuple:
    """Validate a matrix and return its geometry plus quantized data."""
    height = len(matrix)
    if height <= 0:
        raise ValueError("matrix must contain at least one row")
    width = _row_width(matrix[0])
    channels = None
    data = bytearray()
    for row in matrix:
        if len(row) != width:
            raise ValueError("matrix rows must all have the same width")
        channels = _append_row(data, row, channels)
    return width, height, channels, data


def _row_width(row: list) -> int:
    """Return a non-zero matrix row width."""
    width = len(row)
    if width <= 0:
        raise ValueError("matrix rows must contain at least one pixel")
    return width


def _append_row(data: bytearray, row: list, channels: int | None) -> int:
    """Append one matrix row to ``data`` and return the channel count."""
    for pixel in row:
        pixel_channels = _pixel_channels(pixel)
        if channels is None:
            channels = len(pixel_channels)
        elif len(pixel_channels) != channels:
            raise ValueError("matrix pixels must share a channel count")
        for value in pixel_channels:
            data.append(_quantize(value))
    return channels


def _quantize(value: object) -> int:
    """Clamp a normalized scalar and convert it to a byte."""
    if value <= 0:
        return 0
    if value >= 1:
        return 255
    return int(value * 255 + 0.5)


def _draw_columns(
    data: bytearray,
    width: int,
    line_index: int,
    columns: bytearray,
    line_width: int,
    value: int,
) -> None:
    """Draw pre-packed text columns into a line within a frame buffer."""
    x0 = (width - line_width) // 2
    y0 = line_index * _LINE_HEIGHT
    for x in range(line_width):
        bits = columns[x]
        if bits == 0:
            continue
        for y in range(font5x7.HEIGHT):
            if bits & (1 << y):
                data[(y0 + y) * width + x0 + x] = value


def _text_columns(text: str) -> tuple:
    """Pack text into a tight column buffer with collision-aware gaps."""
    if not text:
        return bytearray(0), 0
    glyphs = [bytes(font5x7.char_cols(ch)) for ch in text]
    gaps = [0]
    width = len(glyphs[0])
    for i in range(1, len(glyphs)):
        gap = 1 if glyphs[i - 1][-1] & glyphs[i][0] else 0
        gaps.append(gap)
        width += gap + len(glyphs[i])
    buf = bytearray(width)
    pos = 0
    for i, glyph in enumerate(glyphs):
        pos += gaps[i]
        buf[pos : pos + len(glyph)] = glyph
        pos += len(glyph)
    return buf, width
