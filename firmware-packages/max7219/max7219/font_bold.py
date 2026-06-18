"""Blocky 5x8 font for the time display on the 8-row matrix.

Covers digits 0-9, colon, space, and the letters needed for 12-hour time. Each
byte is one column, bit 0 = top row, bit 7 = bottom row (0xFF = solid column).
2px strokes with squared corners. Unlisted characters fall back to font5x7.

Example — "0" is ``[0xFF, 0xFF, 0xC3, 0xFF, 0xFF]``::

    row0: #####   row4: ## ##
    row1: #####   row5: ## ##
    row2: ## ##    row6: #####
    row3: ## ##    row7: #####
"""

from max7219 import font5x7

_SPACE_WIDTH = 2

# Glyph data: {ascii_code: column bytes}.
_GLYPHS = {
    48: bytes([0xFF, 0xFF, 0xC3, 0xFF, 0xFF]),  # 0
    49: bytes([0xFF, 0xFF]),  # 1  (2 cols, 2px solid bar)
    50: bytes([0xFB, 0xFB, 0xDB, 0xDF, 0xDF]),  # 2
    51: bytes([0xDB, 0xDB, 0xDB, 0xFF, 0xFF]),  # 3
    52: bytes([0x1F, 0x1F, 0x18, 0xFF, 0xFF]),  # 4
    53: bytes([0xDF, 0xDF, 0xDB, 0xFB, 0xFB]),  # 5
    54: bytes([0xFF, 0xFF, 0xDB, 0xFB, 0xFB]),  # 6
    55: bytes([0x03, 0x03, 0x03, 0xFF, 0xFF]),  # 7
    56: bytes([0xFF, 0xFF, 0xDB, 0xFF, 0xFF]),  # 8
    57: bytes([0xDF, 0xDF, 0xDB, 0xFF, 0xFF]),  # 9
    58: bytes([0x6C, 0x6C]),  # :  (2 cols, 2x2 dots)
    32: bytes([0x00, 0x00, 0x00]),  # space (3 cols)
    65: bytes([0xFF, 0xFF, 0x1B, 0xFF, 0xFF]),  # A
    66: bytes([0xFF, 0xFF, 0xDB, 0xDB, 0xE7]),  # B
    67: bytes([0xFF, 0xFF, 0xC3, 0xC3, 0xC3]),  # C
    68: bytes([0xFF, 0xFF, 0xC3, 0xFF, 0xFF]),  # D
    69: bytes([0xFF, 0xFF, 0xDB, 0xDB, 0xDB]),  # E
    70: bytes([0xFF, 0xFF, 0x1B, 0x1B, 0x1B]),  # F
    71: bytes([0xFF, 0xFF, 0xC3, 0xF3, 0xF3]),  # G
    72: bytes([0xFF, 0xFF, 0x18, 0xFF, 0xFF]),  # H
    73: bytes([0xC3, 0xFF, 0xFF, 0xC3, 0xC3]),  # I
    74: bytes([0xC0, 0xC0, 0xC0, 0xFF, 0xFF]),  # J
    76: bytes([0xFF, 0xFF, 0xC0, 0xC0, 0xC0]),  # L
    77: bytes([0xFF, 0xFF, 0x06, 0xFF, 0xFF]),  # M
    78: bytes([0xFF, 0xFF, 0x1C, 0xFF, 0xFF]),  # N
    79: bytes([0xFF, 0xFF, 0xC3, 0xFF, 0xFF]),  # O
    80: bytes([0xFF, 0xFF, 0x1B, 0x1F, 0x1F]),  # P
    82: bytes([0xFF, 0xFF, 0x1B, 0xDF, 0xDF]),  # R
    83: bytes([0xDF, 0xDF, 0xDB, 0xFB, 0xFB]),  # S
    84: bytes([0x03, 0xFF, 0xFF, 0x03, 0x03]),  # T
    85: bytes([0xFF, 0xFF, 0xC0, 0xFF, 0xFF]),  # U
    86: bytes([0x0F, 0x3F, 0xF0, 0x3F, 0x0F]),  # V
    89: bytes([0x07, 0xFF, 0xF8, 0x0F, 0x07]),  # Y
}

# Tiny 3x5 AM/PM glyphs, bottom-aligned at rows 3-7 (bits 3-7), sized to sit as
# a small subscript next to the full-height bold digits.
_TINY_GLYPHS = {
    65: bytes([0xF0, 0x28, 0xF0]),  # A
    80: bytes([0xF8, 0x28, 0x38]),  # P
    77: bytes([0xF8, 0x30, 0xF8]),  # M
}


def char_cols(ch: str) -> memoryview:
    """Return the bold column bytes for one character, trimmed of blank edges.

    Args:
        ch: A single character. Characters with no bold glyph fall back to the
            font5x7 glyph.

    Returns:
        A memoryview over the glyph's lit columns (2-column blank for space).
    """
    g = _GLYPHS.get(ord(ch))
    if g is None:
        return font5x7.char_cols(ch)
    mv = memoryview(g)
    w = len(g)
    start = 0
    while start < w and mv[start] == 0:
        start += 1
    end = w
    while end > start and mv[end - 1] == 0:
        end -= 1
    if start >= end:
        return mv[0:_SPACE_WIDTH]
    return mv[start:end]


def char_cols_tiny(ch: str) -> memoryview:
    """Return the tiny 3-column AM/PM glyph for a character, else the bold glyph.

    Args:
        ch: A single character (``'A'``, ``'M'`` or ``'P'`` have tiny glyphs).

    Returns:
        A memoryview over the glyph's columns.
    """
    g = _TINY_GLYPHS.get(ord(ch))
    if g is not None:
        return memoryview(g)
    return char_cols(ch)
