"""Host CPython in-memory display driver for OledCanvas tests.

Implements the minimal driver surface OledCanvas depends on — ``pixel`` /
``fill`` / ``show`` — and records lit pixels as a ``set`` of (x, y) so tests
can assert on rendered geometry without any hardware or framebuffer encoding.
"""

from __future__ import annotations


class FakeDriver:
    """Records which pixels are lit; mirrors the SSD1306 out-of-bounds no-op."""

    def __init__(self, width: int = 128, height: int = 64) -> None:
        """Allocate an empty lit-pixel set for a widthxheight panel."""
        self.width = width
        self.height = height
        self.lit: set[tuple[int, int]] = set()
        self.show_count = 0

    def pixel(self, x: int, y: int, color: int) -> None:
        """Set or clear (x, y); out-of-bounds coordinates are ignored."""
        if not (0 <= x < self.width and 0 <= y < self.height):
            return
        if color:
            self.lit.add((x, y))
        else:
            self.lit.discard((x, y))

    def fill(self, color: int) -> None:
        """Light or clear every pixel on the panel."""
        if color:
            self.lit = {(x, y) for x in range(self.width) for y in range(self.height)}
        else:
            self.lit.clear()

    def show(self) -> None:
        """Count flushes so tests can assert frames were pushed."""
        self.show_count += 1
