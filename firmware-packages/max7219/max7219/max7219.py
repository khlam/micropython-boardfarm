"""MAX7219 driver for a cascaded 8x8 LED-matrix chain (one logical 8xN display).

A chain of N modules forms an 8 x (8*N) display. The driver holds an in-memory
framebuffer and pushes it to the chain row by row over SPI. Callers light pixels
with ``pixel``/``fill`` or render text with ``show_text``; the ``show_text``,
``clear`` and ``fill`` helpers refresh for you, and ``pixel`` defers to an
explicit ``refresh``.

Hardware conventions for the common red 8x8 modules, baked in here:

- Digit registers 1-8 select the eight rows; the eight data bits select columns.
  Font glyphs are column-major (bit ``r`` of a byte is row ``r``), so ``_blit``
  transposes them into the row-major framebuffer.
- The panels are wired x-mirrored, so display column ``x`` maps to chain column
  ``gx = width - 1 - x``.
- In an SPI cascade the first byte clocked out lands in the *last* module, so a
  row is emitted with the modules in reverse order.
"""

import utime
from micropython import const

from max7219.font5x7 import char_cols as _char_cols

_DEFAULT_MODULES = const(4)
_MODULE_W = const(8)
_ROWS = const(8)
_FLASH_MS = const(250)

# MAX7219 register addresses (datasheet table 2).
_REG_DECODE = const(0x09)
_REG_INTENSITY = const(0x0A)
_REG_SCAN_LIMIT = const(0x0B)
_REG_SHUTDOWN = const(0x0C)
_REG_DISPLAY_TEST = const(0x0D)


class MAX7219:
    """Framebuffer-backed driver for a cascaded MAX7219 chain."""

    def __init__(self, spi: object, cs: object, num_modules: int = _DEFAULT_MODULES) -> None:
        """Initialise the chain, flash every LED as a wiring check, then clear.

        Args:
            spi: A ``machine.SPI`` instance (mode 0) wired to the chain's
                SCK/MOSI.
            cs: A ``machine.Pin`` chip-select, active-low, configured as output.
            num_modules: Number of 8x8 modules in the cascade (default 4).
        """
        self._spi = spi
        self._cs = cs
        self._n = num_modules
        self._width = num_modules * _MODULE_W
        self._buf = bytearray(_ROWS * num_modules)
        self._cmd = bytearray(2 * num_modules)
        self._init_display()

    @property
    def width(self) -> int:
        """Logical display width in pixels (``8 * num_modules``)."""
        return self._width

    def _init_display(self) -> None:
        """Run the power-on register sequence, flash all LEDs, and clear."""
        # Light every LED via the display-test register: a wiring check that
        # ignores the framebuffer, so it works even before the first refresh.
        self._write_all(_REG_DISPLAY_TEST, 0x01)
        utime.sleep_ms(_FLASH_MS)
        self._write_all(_REG_DISPLAY_TEST, 0x00)
        for reg, val in (
            (_REG_SCAN_LIMIT, 0x07),  # scan all eight rows
            (_REG_DECODE, 0x00),  # no BCD decode — this is a matrix, not 7-seg
            (_REG_INTENSITY, 0x07),  # mid brightness
            (_REG_SHUTDOWN, 0x01),  # leave shutdown for normal operation
        ):
            self._write_all(reg, val)
        self.clear()

    def _write_all(self, register: int, data: int) -> None:
        """Send the same register+data word to every module in one CS frame."""
        cmd = self._cmd
        for i in range(self._n):
            cmd[i * 2] = register
            cmd[i * 2 + 1] = data
        self._cs.off()
        self._spi.write(cmd)
        self._cs.on()

    def _write_row(self, row: int) -> None:
        """Send one framebuffer row to the chain (modules reversed for cascade)."""
        cmd = self._cmd
        buf = self._buf
        n = self._n
        reg = row + 1  # digit registers are 1-based
        base = row * n
        for i in range(n):
            cmd[i * 2] = reg
            cmd[i * 2 + 1] = buf[base + (n - 1 - i)]
        self._cs.off()
        self._spi.write(cmd)
        self._cs.on()

    def refresh(self) -> None:
        """Push the whole framebuffer to the display."""
        for row in range(_ROWS):
            self._write_row(row)

    def set_intensity(self, value: int) -> None:
        """Set display brightness (low nibble, 0-15)."""
        self._write_all(_REG_INTENSITY, value & 0x0F)

    def pixel(self, x: int, y: int, *, on: bool = True) -> None:
        """Set or clear one pixel in the framebuffer (no refresh).

        Out-of-range coordinates are ignored. Call ``refresh`` to display.

        Args:
            x: Column, 0 (left) to ``width - 1`` (right).
            y: Row, 0 (top) to 7 (bottom).
            on: True lights the pixel; False clears it.
        """
        if not (0 <= x < self._width and 0 <= y < _ROWS):
            return
        gx = (self._width - 1) - x
        idx = y * self._n + (gx >> 3)
        bit = 1 << (gx & 7)
        if on:
            self._buf[idx] |= bit
        else:
            self._buf[idx] &= ~bit & 0xFF

    def fill(self, *, on: bool = True) -> None:
        """Set every pixel on (or off) and refresh — a quick all-LEDs check."""
        value = 0xFF if on else 0x00
        buf = self._buf
        for i in range(len(buf)):
            buf[i] = value
        self.refresh()

    def clear(self) -> None:
        """Zero the framebuffer and refresh the display."""
        self._clear_buf()
        self.refresh()

    def show_text(self, text: str) -> None:
        """Render ``text`` and refresh.

        Text is centered when it fits in ``width``; longer text left-aligns and
        clips at the right edge.
        """
        cols, width = _text_columns(text)
        offset = max((self._width - width) // 2, 0)
        self._clear_buf()
        self._blit(cols, width, offset)
        self.refresh()

    def _clear_buf(self) -> None:
        """Zero the framebuffer without refreshing."""
        buf = self._buf
        for i in range(len(buf)):
            buf[i] = 0

    def _blit(self, cols: bytes, width: int, offset: int) -> None:
        """Transpose column-major glyph bytes into the framebuffer at ``offset``.

        Args:
            cols: Column bytes (each bit a row), left to right.
            width: Number of columns available in ``cols``.
            offset: Destination column where ``cols[0]`` lands.
        """
        buf = self._buf
        n = self._n
        full = self._width
        for col in range(width):
            byte = cols[col]
            if byte == 0:
                continue
            gx = (full - 1) - (col + offset)
            if gx < 0:
                break  # off the right edge — every later column is too
            m = gx >> 3
            bit = 1 << (gx & 7)
            for row in range(_ROWS):
                if byte & (1 << row):
                    buf[row * n + m] |= bit


def _text_columns(text: str) -> tuple:
    """Pack ``text`` into a tight column buffer.

    Glyphs sit flush; a single blank separator column is inserted between two
    glyphs only when their touching edge columns share a lit row (their bytes
    AND to non-zero), which keeps neighbouring letters from merging.

    Args:
        text: The string to render.

    Returns:
        ``(columns, width)`` — a ``bytearray`` of column bytes and its length.
    """
    if not text:
        return bytearray(0), 0
    glyphs = [bytes(_char_cols(ch)) for ch in text]
    gaps = [0]
    width = len(glyphs[0])
    for i in range(1, len(glyphs)):
        gap = 1 if glyphs[i - 1][-1] & glyphs[i][0] else 0
        gaps.append(gap)
        width += gap + len(glyphs[i])
    buf = bytearray(width)
    pos = 0
    for i, glyph in enumerate(glyphs):
        pos += gaps[i]  # 0 or 1 blank separator column
        buf[pos : pos + len(glyph)] = glyph
        pos += len(glyph)
    return buf, width
