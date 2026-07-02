"""Packed and matrix frame primitives for pixel display rendering."""

_CHANNELS_INTENSITY = 1


class MatrixFrame:
    """Row-major n-channel pixel matrix backed by byte values."""

    def __init__(self, width: int, height: int, channels: int, data: bytearray) -> None:
        """Store matrix frame geometry and pixel bytes.

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
    def blank(
        cls,
        width: int,
        height: int,
        channels: int = _CHANNELS_INTENSITY,
    ) -> "MatrixFrame":
        """Create an all-off matrix frame."""
        return cls(width, height, channels, bytearray(width * height * channels))

    @classmethod
    def from_matrix(cls, matrix: list) -> "MatrixFrame":
        """Create a frame from a 2D intensity or 3D channel matrix.

        Args:
            matrix: Rows of pixels. A pixel may be a normalized scalar or a
                sequence of normalized channel values.

        Returns:
            A frame with values quantized to bytes.
        """
        width, height, channels, data = _matrix_geometry_and_data(matrix)
        return cls(width, height, channels, data)

    def value_at(self, x: int, y: int, channel: int = 0) -> int:
        """Return one byte value from the frame."""
        return self.data[(y * self.width + x) * self.channels + channel]


class Frame:
    """Exact-size packed monochrome frame with pixel-box drawing support."""

    def __init__(
        self,
        width: int,
        height: int,
        intensity: int = 255,
        *,
        stride: int | None = None,
        data: bytearray | None = None,
    ) -> None:
        """Allocate or wrap a packed monochrome frame.

        Args:
            width: Frame width in pixels.
            height: Frame height in pixels.
            intensity: Shared byte value for lit pixels.
            stride: Packed bytes per row. Defaults to the minimum stride.
            data: Optional row-major packed bits, ``height * stride`` bytes.

        Raises:
            ValueError: If geometry, stride, or data length is invalid.
        """
        if width <= 0 or height <= 0:
            raise ValueError("frame geometry must be positive")
        min_stride = (width + 7) // 8
        if stride is None:
            stride = min_stride
        if stride < min_stride:
            raise ValueError("packed stride is too small")
        if data is None:
            data = bytearray(height * stride)
        elif len(data) != height * stride:
            raise ValueError("packed data length does not match geometry")
        self.width = width
        self.height = height
        self.channels = _CHANNELS_INTENSITY
        self.stride = stride
        self.data = data
        self.intensity = _clamp_byte(intensity)

    @classmethod
    def from_packed(
        cls,
        width: int,
        height: int,
        stride: int,
        data: bytearray,
        intensity: int = 255,
    ) -> "Frame":
        """Wrap packed row-major data in a frame object."""
        return cls(width, height, intensity, stride=stride, data=data)

    def __setitem__(self, key: object, content: object) -> None:
        """Draw content into a matrix-order pixel box."""
        if not isinstance(key, tuple) or len(key) != 2:
            raise TypeError("frame assignment expects frame[y_slice, x_slice]")
        y0, y1 = _slice_bounds(key[0], self.height, "y")
        x0, x1 = _slice_bounds(key[1], self.width, "x")
        draw = getattr(content, "draw", None)
        if draw is None:
            raise TypeError("assigned content must expose draw(frame, x, y, width, height)")
        draw(self, x0, y0, x1 - x0, y1 - y0)

    def clear(self) -> None:
        """Turn off every packed pixel."""
        for i in range(len(self.data)):
            self.data[i] = 0

    def pixel(self, x: int, y: int, *, on: bool = True) -> None:
        """Set or clear one pixel, clipping coordinates outside the frame."""
        if x < 0 or y < 0 or x >= self.width or y >= self.height:
            return
        self.set_pixel_unchecked(x, y, on=on)

    def value_at(self, x: int, y: int, channel: int = 0) -> int:
        """Return the shared byte intensity when the packed bit is lit."""
        if channel != 0:
            raise IndexError("packed frames expose one channel")
        if x < 0 or y < 0 or x >= self.width or y >= self.height:
            raise IndexError("packed frame coordinate out of range")
        if self.data[(y * self.stride) + (x >> 3)] & (1 << (x & 7)):
            return self.intensity
        return 0

    def unpack(self) -> MatrixFrame:
        """Return an equivalent byte-per-pixel matrix frame."""
        data = bytearray(self.width * self.height)
        if self.intensity <= 0:
            return MatrixFrame(self.width, self.height, self.channels, data)
        for y in range(self.height):
            packed_base = y * self.stride
            unpacked_base = y * self.width
            for x in range(self.width):
                if self.data[packed_base + (x >> 3)] & (1 << (x & 7)):
                    data[unpacked_base + x] = self.intensity
        return MatrixFrame(self.width, self.height, self.channels, data)

    def copy(self) -> "Frame":
        """Return a byte-for-byte copy of the packed frame."""
        return Frame.from_packed(
            self.width,
            self.height,
            self.stride,
            bytearray(self.data),
            self.intensity,
        )

    def set_pixel_unchecked(self, x: int, y: int, *, on: bool = True) -> None:
        """Set or clear one in-bounds packed pixel."""
        index = (y * self.stride) + (x >> 3)
        mask = 1 << (x & 7)
        if on:
            self.data[index] |= mask
        else:
            self.data[index] &= 0xFF ^ mask


def _slice_bounds(item: object, limit: int, axis: str) -> tuple:
    """Return checked non-empty slice bounds for one frame axis."""
    if not isinstance(item, slice):
        raise TypeError(axis + " index must be a slice")
    if item.step is not None:
        raise ValueError(axis + " slice step is not supported")
    start = 0 if item.start is None else item.start
    stop = limit if item.stop is None else item.stop
    if not isinstance(start, int) or not isinstance(stop, int):
        raise TypeError(axis + " slice bounds must be integers")
    if start < 0 or stop < 0:
        raise ValueError(axis + " slice must not use negative indexes")
    if start >= stop:
        raise ValueError(axis + " slice must not be empty")
    if stop > limit:
        raise ValueError(axis + " slice exceeds frame bounds")
    return start, stop


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


def _clamp_byte(value: int) -> int:
    """Clamp an integer-like value to one byte."""
    if value <= 0:
        return 0
    if value >= 255:
        return 255
    return int(value)
