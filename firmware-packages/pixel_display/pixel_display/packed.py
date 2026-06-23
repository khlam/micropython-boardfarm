"""Packed monochrome drawing primitives for pixel displays."""

from pixel_display.frame import Frame

_CHANNELS_INTENSITY = 1


class PackedFrame:
    """One-bit row-major frame with a shared byte intensity."""

    def __init__(
        self,
        width: int,
        height: int,
        stride: int,
        data: bytearray,
        intensity: int = 255,
    ) -> None:
        """Store packed pixels and their shared intensity.

        Args:
            width: Frame width in pixels.
            height: Frame height in pixels.
            stride: Packed bytes per row.
            data: Row-major packed bits, ``height * stride`` bytes long.
            intensity: Shared byte value for lit pixels.

        Raises:
            ValueError: If geometry, stride, or data length is invalid.
        """
        if width <= 0 or height <= 0:
            raise ValueError("frame geometry must be positive")
        min_stride = (width + 7) // 8
        if stride < min_stride:
            raise ValueError("packed stride is too small")
        if len(data) != height * stride:
            raise ValueError("packed data length does not match geometry")
        self.width = width
        self.height = height
        self.channels = _CHANNELS_INTENSITY
        self.stride = stride
        self.data = data
        self.intensity = _clamp_byte(intensity)

    def value_at(self, x: int, y: int, channel: int = 0) -> int:
        """Return the shared byte intensity when the packed bit is lit."""
        if channel != 0:
            raise IndexError("packed frames expose one channel")
        if x < 0 or y < 0 or x >= self.width or y >= self.height:
            raise IndexError("packed frame coordinate out of range")
        if self.data[(y * self.stride) + (x >> 3)] & (1 << (x & 7)):
            return self.intensity
        return 0

    def unpack(self) -> Frame:
        """Return an equivalent byte-per-pixel ``Frame``."""
        data = bytearray(self.width * self.height)
        if self.intensity <= 0:
            return Frame(self.width, self.height, self.channels, data)
        for y in range(self.height):
            packed_base = y * self.stride
            unpacked_base = y * self.width
            for x in range(self.width):
                if self.data[packed_base + (x >> 3)] & (1 << (x & 7)):
                    data[unpacked_base + x] = self.intensity
        return Frame(self.width, self.height, self.channels, data)

    def copy(self) -> "PackedFrame":
        """Return a byte-for-byte copy of the packed frame."""
        return PackedFrame(
            self.width,
            self.height,
            self.stride,
            bytearray(self.data),
            self.intensity,
        )


class Canvas:
    """Mutable packed monochrome drawing surface."""

    def __init__(self, width: int, height: int, intensity: int = 255) -> None:
        """Allocate a blank packed drawing surface."""
        if width <= 0 or height <= 0:
            raise ValueError("canvas geometry must be positive")
        self.width = width
        self.height = height
        self.channels = _CHANNELS_INTENSITY
        self.stride = (width + 7) // 8
        self.data = bytearray(self.height * self.stride)
        self.intensity = _clamp_byte(intensity)

    def clear(self) -> None:
        """Turn off every packed pixel."""
        for i in range(len(self.data)):
            self.data[i] = 0

    def pixel(self, x: int, y: int, *, on: bool = True) -> None:
        """Set or clear one pixel, clipping coordinates outside the canvas."""
        if x < 0 or y < 0 or x >= self.width or y >= self.height:
            return
        index = (y * self.stride) + (x >> 3)
        mask = 1 << (x & 7)
        if on:
            self.data[index] |= mask
        else:
            self.data[index] &= 0xFF ^ mask

    def value_at(self, x: int, y: int, channel: int = 0) -> int:
        """Return one pixel value using ``PackedFrame`` semantics."""
        if channel != 0:
            raise IndexError("packed frames expose one channel")
        if x < 0 or y < 0 or x >= self.width or y >= self.height:
            raise IndexError("canvas coordinate out of range")
        if self.data[(y * self.stride) + (x >> 3)] & (1 << (x & 7)):
            return self.intensity
        return 0

    def frame(self) -> PackedFrame:
        """Freeze the current canvas pixels into a packed frame copy."""
        return PackedFrame(
            self.width,
            self.height,
            self.stride,
            bytearray(self.data),
            self.intensity,
        )


def _clamp_byte(value: int) -> int:
    """Clamp an integer-like value to one byte."""
    if value <= 0:
        return 0
    if value >= 255:
        return 255
    return int(value)
