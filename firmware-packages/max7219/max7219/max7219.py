"""MAX7219 driver for cascaded 8x8 LED matrix modules with text + scroll.

Hardware quirks baked in here:

- Digit registers 1-8 drive matrix rows 0-7; data bits drive columns. Font column
  bytes encode rows as bits, so rendering transposes columns -> rows (see _blit).
- The display is x-axis mirrored, so display x maps to global bit ``gx = 31 - x``.
- In an SPI cascade the first byte shifts to the *last* module, so _write_row
  emits modules in reverse order.
"""

import utime
from micropython import const

from max7219.font5x7 import char_cols as _default_char_cols

_DEFAULT_MODULES = const(4)
_DISPLAY_W = const(32)
_CELL = const(8)  # one 8x8 module
_TIME_W = const(24)  # _DISPLAY_W - _CELL: columns reserved for the time text
_TEST_FLASH_MS = const(500)

# MAX7219 registers
_DECODE_MODE = const(0x09)
_INTENSITY = const(0x0A)
_SCAN_LIMIT = const(0x0B)
_SHUTDOWN = const(0x0C)
_DISPLAY_TEST = const(0x0D)


class MAX7219:
    """Framebuffer-backed driver for a cascaded MAX7219 chain.

    Only one animation is active at a time: ``show_*`` methods render immediately
    and clear the animation buffer; ``set_*`` methods load the animation buffer
    for ``scroll_step``/``wiggle_step`` to advance.
    """

    def __init__(self, spi: object, cs: object, num_modules: int = _DEFAULT_MODULES) -> None:
        """Initialise the chain and clear the display.

        Args:
            spi: A ``machine.SPI`` instance (mode 0) wired to the chain's
                SCK/MOSI.
            cs: A ``machine.Pin`` chip-select, active-low, configured as output.
            num_modules: Number of 8x8 modules in the cascade (default 4).
        """
        self._spi = spi
        self._cs = cs
        self._n = num_modules
        self._buf = bytearray(8 * num_modules)
        self._cmd = bytearray(2 * num_modules)
        self._text_buf: object = None
        self._text_len = 0
        self._scroll_pos = 0
        self._wiggle_max = 0
        self._wiggle_dir = 1
        self._init_display()

    def _init_display(self) -> None:
        """Run the power-on register sequence and clear all rows."""
        # Flash all LEDs via the display-test register to confirm SPI works.
        self._write_all(_DISPLAY_TEST, 0x01)
        utime.sleep_ms(_TEST_FLASH_MS)
        self._write_all(_DISPLAY_TEST, 0x00)
        for reg, val in (
            (_SCAN_LIMIT, 0x07),
            (_DECODE_MODE, 0x00),
            (_INTENSITY, 0x07),
            (_SHUTDOWN, 0x01),
        ):
            self._write_all(reg, val)
        for row in range(8):
            self._write_all(row + 1, 0x00)

    def _write_all(self, register: int, data: int) -> None:
        """Send the same register+data command to all modules at once."""
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
        for row in range(8):
            self._write_row(row)

    @property
    def buf(self) -> bytearray:
        """Raw framebuffer bytes (8 rows x n modules)."""
        return self._buf

    @property
    def n(self) -> int:
        """Number of 8x8 modules in the cascade."""
        return self._n

    def clear_buf(self) -> None:
        """Zero the framebuffer without refreshing."""
        buf = self._buf
        for i in range(len(buf)):
            buf[i] = 0

    def clear(self) -> None:
        """Clear the framebuffer and refresh the display."""
        self.clear_buf()
        self.refresh()

    def set_intensity(self, val: int) -> None:
        """Set display brightness (0-15)."""
        self._write_all(_INTENSITY, val & 0x0F)

    def _blit(self, cols_buf: bytearray, width: int, offset: int, max_w: int, src: int = 0) -> None:
        """Transpose column bytes into the framebuffer at a horizontal offset.

        Args:
            cols_buf: Buffer of column bytes (each bit a row).
            width: Number of source columns available from ``src``.
            offset: Destination column at which column ``src`` lands.
            max_w: Stop after this many destination columns.
            src: First source column index to read.
        """
        buf = self._buf
        n = self._n
        end = min(width, max_w)
        for x in range(end):
            col_byte = cols_buf[src + x]
            if col_byte == 0:
                continue
            gx = (_DISPLAY_W - 1) - (x + offset)
            if gx < 0:
                break
            m = gx >> 3
            bit = gx & 7
            for row in range(8):
                if col_byte & (1 << row):
                    buf[row * n + m] |= 1 << bit

    def _build_cols(self, text: str, char_cols_fn: object = None) -> tuple:
        """Build a tightly packed column buffer for ``text``.

        A 1px blank separator is inserted between two glyphs only when the last
        column of the left glyph and the first column of the right glyph share a
        lit pixel on any row (their bytes AND to non-zero).

        Args:
            text: The string to render.
            char_cols_fn: Glyph lookup; defaults to the font5x7 lookup.

        Returns:
            ``(buffer, width)`` where ``buffer`` is a bytearray of column bytes.
        """
        if not text:
            return bytearray(0), 0
        if char_cols_fn is None:
            char_cols_fn = _default_char_cols
        glyphs = [char_cols_fn(ch) for ch in text]
        gaps = _gap_flags(glyphs)
        total = sum(len(g) for g in glyphs) + sum(gaps)
        buf = bytearray(total)
        pos = 0
        for i, cols in enumerate(glyphs):
            pos += gaps[i]  # 0 or 1 blank separator column
            for b in cols:
                buf[pos] = b
                pos += 1
        return buf, total

    def show_text(self, text: str, char_cols_fn: object = None) -> None:
        """Render ``text`` centered and static (no animation)."""
        cols_buf, text_cols = self._build_cols(text, char_cols_fn)
        offset = max((_DISPLAY_W - text_cols) // 2, 0)
        self.clear_buf()
        self._blit(cols_buf, text_cols, offset, _DISPLAY_W)
        self.refresh()
        self._text_buf = None

    def show_auto(self, text: str, char_cols_fn: object = None) -> None:
        """Render ``text`` centered if it fits in 32px, otherwise set up a wiggle."""
        cols_buf, text_cols = self._build_cols(text, char_cols_fn)
        if text_cols > _DISPLAY_W:
            self._text_buf = cols_buf
            self._text_len = text_cols
            self._scroll_pos = 0
            self._wiggle_max = text_cols - _DISPLAY_W
            self._wiggle_dir = 1
            self._render_window()
        else:
            offset = (_DISPLAY_W - text_cols) // 2
            self.clear_buf()
            self._blit(cols_buf, text_cols, offset, _DISPLAY_W)
            self.refresh()
            self._text_buf = None

    def show_time(
        self,
        time_text: str,
        suffix: str,
        time_font: object = None,
        suffix_font: object = None,
    ) -> None:
        """Render time in the first 24 columns and AM/PM in the last 8-col cell."""
        time_cols, time_w = self._build_cols(time_text, time_font)
        suffix_cols, suffix_w = self._build_cols(suffix, suffix_font)
        self.clear_buf()
        t_off = max((_TIME_W - time_w) // 2, 0)
        self._blit(time_cols, time_w, t_off, _TIME_W)
        s_off = _TIME_W + (_CELL - suffix_w) // 2
        self._blit(suffix_cols, suffix_w, s_off, _DISPLAY_W)
        self.refresh()
        self._text_buf = None

    def set_text(self, text: str) -> None:
        """Load ``text`` for right-to-left scrolling (blank padding each side)."""
        cols_buf, text_cols = self._build_cols(text)
        total = _DISPLAY_W + text_cols + _DISPLAY_W
        tb = bytearray(total)
        for i in range(text_cols):
            tb[_DISPLAY_W + i] = cols_buf[i]
        self._text_buf = tb
        self._text_len = total
        self._scroll_pos = 0
        self._wiggle_max = 0
        self._render_window()

    def set_text_wiggle(self, text: str) -> None:
        """Load ``text`` for side-to-side wiggle when it overflows 32px."""
        cols_buf, text_cols = self._build_cols(text)
        self._text_buf = cols_buf
        self._text_len = text_cols
        self._scroll_pos = 0
        self._wiggle_max = max(text_cols - _DISPLAY_W, 0)
        self._wiggle_dir = 1
        self._render_window()

    def scroll_step(self) -> None:
        """Advance a right-to-left scroll by one pixel and refresh."""
        if self._text_buf is None:
            return
        self._scroll_pos += 1
        if self._scroll_pos > self._text_len - _DISPLAY_W:
            self._scroll_pos = 0
        self._render_window()

    def wiggle_step(self) -> None:
        """Move the view one pixel in the current direction, reversing at edges."""
        if self._text_buf is None or self._wiggle_max == 0:
            return
        self._scroll_pos += self._wiggle_dir
        if self._scroll_pos >= self._wiggle_max:
            self._scroll_pos = self._wiggle_max
            self._wiggle_dir = -1
        elif self._scroll_pos <= 0:
            self._scroll_pos = 0
            self._wiggle_dir = 1
        self._render_window()

    def _render_window(self) -> None:
        """Render the 32-column window at the current scroll position and refresh."""
        self.clear_buf()
        self._blit(self._text_buf, _DISPLAY_W, 0, _DISPLAY_W, self._scroll_pos)
        self.refresh()


def _gap_flags(glyphs: list) -> list:
    """Return per-glyph blank-separator flags for tight horizontal packing.

    ``flags[i]`` is 1 when glyph ``i`` must be preceded by a 1px blank column —
    i.e. the last column of glyph ``i-1`` and the first column of glyph ``i``
    share a lit row (their bytes AND to non-zero). The first glyph never gets a
    leading gap.

    Args:
        glyphs: Per-character column buffers (each a bytes-like of column bytes).

    Returns:
        A list of 0/1 the same length as ``glyphs``.
    """
    flags = [0]
    for i in range(1, len(glyphs)):
        prev = glyphs[i - 1]
        flags.append(1 if prev[len(prev) - 1] & glyphs[i][0] else 0)
    return flags
