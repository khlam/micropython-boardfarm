"""Host CPython stub of MicroPython's ``framebuf`` module."""

from __future__ import annotations

MONO_VLSB = 0


class FrameBuffer:
    """Minimal vertical-LSB monochrome framebuffer used by display tests."""

    def __init__(self, buffer: bytearray, width: int, height: int, format: int) -> None:  # noqa: A002
        """Store the caller-owned framebuffer and geometry.

        Args:
            buffer: Mutable framebuffer storage.
            width: Width in pixels.
            height: Height in pixels.
            format: Framebuffer encoding constant.
        """
        self.buffer = buffer
        self.width = width
        self.height = height
        self.format = format

    def fill(self, color: int) -> None:
        """Set every framebuffer bit to ``color``.

        Args:
            color: Zero clears the buffer; any other value sets every bit.
        """
        value = 0xFF if color else 0x00
        for index in range(len(self.buffer)):
            self.buffer[index] = value

    def pixel(self, x: int, y: int, color: int | None = None) -> int | None:
        """Get or set one pixel in MONO_VLSB layout.

        Args:
            x: Horizontal pixel coordinate.
            y: Vertical pixel coordinate.
            color: New pixel value, or None to read it.

        Returns:
            The current pixel value when reading, otherwise None.
        """
        if not (0 <= x < self.width and 0 <= y < self.height):
            return None
        index = x + (y // 8) * self.width
        mask = 1 << (y % 8)
        if color is None:
            return int(bool(self.buffer[index] & mask))
        if color:
            self.buffer[index] |= mask
        else:
            self.buffer[index] &= ~mask
        return None

    def text(self, string: str, x: int, y: int, color: int = 1) -> None:
        """Draw deterministic placeholder glyphs for host-side assertions.

        The stub does not reproduce MicroPython's built-in font. Each non-space
        character becomes a five-by-seven outline so tests can verify that text
        changes and flushes the framebuffer.

        Args:
            string: Text to draw.
            x: Left pixel coordinate.
            y: Top pixel coordinate.
            color: Pixel value used for each placeholder glyph.
        """
        for char_index, char in enumerate(string):
            if char == " ":
                continue
            left = x + char_index * 8
            for dx in range(5):
                self.pixel(left + dx, y, color)
                self.pixel(left + dx, y + 6, color)
            for dy in range(1, 6):
                self.pixel(left, y + dy, color)
                self.pixel(left + 4, y + dy, color)
