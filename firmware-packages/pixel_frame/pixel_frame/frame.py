"""Packed monochrome frame primitive for pixel display rendering."""


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
        self.stride = stride
        self.data = data
        self.intensity = _clamp_byte(intensity)

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

    def pixel(self, x: int, y: int) -> None:
        """Light one pixel, clipping coordinates outside the frame."""
        if x < 0 or y < 0 or x >= self.width or y >= self.height:
            return
        self.set_pixel_unchecked(x, y)

    def value_at(self, x: int, y: int) -> int:
        """Return the shared byte intensity when the packed bit is lit."""
        if x < 0 or y < 0 or x >= self.width or y >= self.height:
            raise IndexError("packed frame coordinate out of range")
        if self.data[(y * self.stride) + (x >> 3)] & (1 << (x & 7)):
            return self.intensity
        return 0

    def copy(self) -> "Frame":
        """Return a byte-for-byte copy of the packed frame."""
        return Frame(
            self.width,
            self.height,
            self.intensity,
            stride=self.stride,
            data=bytearray(self.data),
        )

    def set_pixel_unchecked(self, x: int, y: int) -> None:
        """Light one in-bounds packed pixel."""
        self.data[(y * self.stride) + (x >> 3)] |= 1 << (x & 7)


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


def _clamp_byte(value: int) -> int:
    """Clamp an integer-like value to one byte."""
    if value <= 0:
        return 0
    if value >= 255:
        return 255
    return int(value)
