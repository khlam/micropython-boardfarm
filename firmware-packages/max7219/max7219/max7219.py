"""MAX7219 driver for two 8x32 panels stacked into one 16x32 display.

Two FC-16 panels (four cascaded 8x8 modules each) hang on a single SPI chain,
MCU -> top panel -> bottom panel. The driver hides that cascade: callers work in
human-visual coordinates on one 16-row x 32-column framebuffer (``y = 0`` is the
top row of the top panel, ``x = 0`` the leftmost column) and never think about
which chip a pixel lands on.

The framebuffer holds the image exactly as the eye should see it; ``refresh``
translates it into the eight per-chip-row SPI frames, applying every hardware
quirk at that boundary:

- The chain has eight 8x8 chips. Chips 0-3 form the top panel, 4-7 the bottom
  panel (chip 0 sits nearest the MCU's DIN).
- In an SPI cascade the first byte clocked out lands in the *last* chip, so each
  frame is emitted with the chips in reverse order.
- ``_MIRROR_X`` / ``_FLIP_Y`` correct the panels' physical mounting (see below).
"""

import utime
from micropython import const

from max7219.font5x7 import char_cols as _char_cols

_PANEL_W = const(32)  # one 8x32 panel = four cascaded 8x8 chips
_PANEL_H = const(8)
_CHIPS_PER_PANEL = const(4)
_PANELS = const(2)  # two panels stacked vertically -> 16x32
_NUM_CHIPS = const(_CHIPS_PER_PANEL * _PANELS)
_WIDTH = const(_PANEL_W)
_HEIGHT = const(_PANEL_H * _PANELS)
_BYTES_PER_ROW = const(_WIDTH // 8)
_FONT_ROWS = const(7)
_FLASH_MS = const(250)

# Orientation knobs — the two bring-up adjustments for this matrix. The pixels
# live in the framebuffer the right way up; these flip how that image is mapped
# onto the silicon to match how the panels are physically mounted:
#   _MIRROR_X — flip if text reads mirrored (backwards) left-to-right.
#   _FLIP_Y   — flip if text reads upside down.
# Both default to the values that render right-side-up on the clock's panels.
_MIRROR_X = False
_FLIP_Y = True

# MAX7219 register addresses (datasheet table 2).
_REG_DECODE = const(0x09)
_REG_INTENSITY = const(0x0A)
_REG_SCAN_LIMIT = const(0x0B)
_REG_SHUTDOWN = const(0x0C)
_REG_DISPLAY_TEST = const(0x0F)


class MAX7219:
    """Framebuffer-backed driver for the stacked 16x32 MAX7219 display."""

    def __init__(self, spi: object, cs: object) -> None:
        """Initialise the chain, flash every LED as a wiring check, then clear.

        Args:
            spi: A ``machine.SPI`` instance (mode 0) wired to the chain's
                SCK/MOSI.
            cs: A ``machine.Pin`` chip-select, active-low, configured as output.
        """
        self._spi = spi
        self._cs = cs
        # Visual framebuffer: one bit per pixel, row-major, _BYTES_PER_ROW bytes
        # per row. Bit (1 << (x & 7)) of byte (y * _BYTES_PER_ROW + x // 8) is
        # the pixel at visual (x, y).
        self._fb = bytearray(_HEIGHT * _BYTES_PER_ROW)
        self._cmd = bytearray(2 * _NUM_CHIPS)
        self._init_display()

    @property
    def width(self) -> int:
        """Logical display width in pixels (32)."""
        return _WIDTH

    @property
    def height(self) -> int:
        """Logical display height in pixels (16)."""
        return _HEIGHT

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
        """Send the same register+data word to every chip in one CS frame."""
        cmd = self._cmd
        for i in range(_NUM_CHIPS):
            cmd[i * 2] = register
            cmd[i * 2 + 1] = data
        self._cs.off()
        self._spi.write(cmd)
        self._cs.on()

    def refresh(self) -> None:
        """Translate the visual framebuffer to the chain and push it out.

        One SPI frame per chip-row (eight total): each frame carries that row's
        byte for all eight chips, chips emitted in reverse so the cascade lands
        them in physical order.
        """
        fb = self._fb
        cmd = self._cmd
        for chip_row in range(_PANEL_H):
            reg = chip_row + 1  # digit registers are 1-based
            for chip in range(_NUM_CHIPS):
                panel = chip // _CHIPS_PER_PANEL
                col_chip = chip % _CHIPS_PER_PANEL
                src_row = (_PANEL_H - 1 - chip_row) if _FLIP_Y else chip_row
                vy = panel * _PANEL_H + src_row
                row_base = vy * _BYTES_PER_ROW
                byte = 0
                for bit in range(8):
                    nat_x = col_chip * 8 + bit  # 0..31, left-to-right on the panel
                    vx = (_WIDTH - 1 - nat_x) if _MIRROR_X else nat_x
                    if fb[row_base + (vx >> 3)] & (1 << (vx & 7)):
                        byte |= 1 << bit
                pos = _NUM_CHIPS - 1 - chip  # reverse for the SPI cascade
                cmd[pos * 2] = reg
                cmd[pos * 2 + 1] = byte
            self._cs.off()
            self._spi.write(cmd)
            self._cs.on()

    def set_intensity(self, value: int) -> None:
        """Set display brightness (low nibble, 0-15)."""
        self._write_all(_REG_INTENSITY, value & 0x0F)

    def pixel(self, x: int, y: int, *, on: bool = True) -> None:
        """Set or clear one pixel in the framebuffer (no refresh).

        Out-of-range coordinates are ignored. Call ``refresh`` to display.

        Args:
            x: Column, 0 (left) to 31 (right).
            y: Row, 0 (top) to 15 (bottom).
            on: True lights the pixel; False clears it.
        """
        if not (0 <= x < _WIDTH and 0 <= y < _HEIGHT):
            return
        idx = y * _BYTES_PER_ROW + (x >> 3)
        bit = 1 << (x & 7)
        if on:
            self._fb[idx] |= bit
        else:
            self._fb[idx] &= ~bit & 0xFF

    def fill(self, *, on: bool = True) -> None:
        """Set every pixel on (or off) and refresh — a quick all-LEDs check."""
        value = 0xFF if on else 0x00
        fb = self._fb
        for i in range(len(fb)):
            fb[i] = value
        self.refresh()

    def clear_buf(self) -> None:
        """Zero the framebuffer without refreshing (compose, then ``refresh``)."""
        fb = self._fb
        for i in range(len(fb)):
            fb[i] = 0

    def clear(self) -> None:
        """Zero the framebuffer and refresh the display."""
        self.clear_buf()
        self.refresh()

    def draw_text(self, text: str, x: int, y: int) -> int:
        """Blit ``text`` into the framebuffer with its top-left at ``(x, y)``.

        Does not clear or refresh, so callers can compose several strings before
        a single ``refresh``. Pixels off the edge are clipped.

        Args:
            text: The string to render in the 5x7 font.
            x: Left column of the first glyph.
            y: Top row of the glyphs.

        Returns:
            The rendered pixel width (see ``text_width``).
        """
        cols, width = _text_columns(text)
        for col in range(width):
            byte = cols[col]
            if byte == 0:
                continue
            vx = x + col
            for row in range(_FONT_ROWS):
                if byte & (1 << row):
                    self.pixel(vx, y + row)
        return width

    def text_width(self, text: str) -> int:
        """Pixel width ``text`` occupies in the 5x7 font (for centering)."""
        return _text_columns(text)[1]

    def show_lines(self, top: str, bottom: str) -> None:
        """Render one centered string on each panel and refresh.

        Args:
            top: Text for the top panel (visual rows 0-7).
            bottom: Text for the bottom panel (visual rows 8-15).
        """
        self.clear_buf()
        self.draw_text(top, self._center_x(top), 0)
        self.draw_text(bottom, self._center_x(bottom), _PANEL_H)
        self.refresh()

    def _center_x(self, text: str) -> int:
        """Left column that horizontally centers ``text`` (0 if it overflows)."""
        return max((_WIDTH - self.text_width(text)) // 2, 0)


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
