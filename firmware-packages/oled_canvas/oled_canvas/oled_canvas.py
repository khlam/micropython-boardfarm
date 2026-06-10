"""MCU-micropython layout layer that arranges and scales content to fit a panel.

``OledCanvas`` wraps any driver exposing ``pixel(x, y, c)`` / ``fill(c)`` /
``show()`` (e.g. the ``ssd1306`` driver — passed in, not imported, so this
package stays driver-agnostic). It is constructed with the panel's width and
height and owns all geometry: text rendering from the bundled 5x8 font,
integer up-scaling, measurement, auto-fit, and centering. Callers describe
*what* to draw, never raw pixel coordinates that assume a fixed panel size.

``BouncingText`` is a small reusable sprite: a string that moves and reflects
off the panel edges, auto-scaled to fit when no scale is given.
"""

import random

from oled_canvas import font

_GAP = 1  # blank column between glyphs, in unscaled font pixels


class OledCanvas:
    """Auto-arranging text/layout surface over a raw monochrome driver."""

    def __init__(self, driver: object, width: int, height: int) -> None:
        """Bind the canvas to a driver and the panel's pixel dimensions.

        Args:
            driver: Object exposing ``pixel(x, y, c)``, ``fill(c)``, ``show()``.
            width: Panel width in pixels.
            height: Panel height in pixels.
        """
        self.driver = driver
        self.width = width
        self.height = height

    def clear(self) -> None:
        """Blank the whole surface."""
        self.driver.fill(0)

    def show(self) -> None:
        """Flush the surface to the panel."""
        self.driver.show()

    def text_width(self, s: str, scale: int = 1) -> int:
        """Return the advance width of ``s`` at ``scale``, including inter-glyph gaps."""
        return len(s) * (font.WIDTH + _GAP) * scale

    def text_height(self, scale: int = 1) -> int:
        """Return the cell height of one text row at ``scale``."""
        return font.HEIGHT * scale

    def fit_scale(self, s: str, max_w: int, max_h: int) -> int:
        """Return the largest integer scale (≥1) at which ``s`` fits ``max_w``x``max_h``.

        Never returns below 1 — an over-long string is drawn at scale 1 and
        clipped rather than vanishing.
        """
        if not s:
            return 1
        w_scale = max_w // self.text_width(s, 1)
        h_scale = max_h // self.text_height(1)
        return max(1, min(w_scale, h_scale))

    def char(self, ch: str, x: int, y: int, scale: int = 1, color: int = 1) -> None:
        """Draw one glyph with its top-left at (x, y), each pixel a ``scale``² block."""
        bitmap = font.glyph(ch)
        for col in range(font.WIDTH):
            bits = bitmap[col]
            for row in range(font.HEIGHT):
                if bits & (1 << row):
                    self._block(x + col * scale, y + row * scale, scale, color)

    def text(self, s: str, x: int, y: int, scale: int = 1, color: int = 1) -> None:
        """Draw ``s`` left-to-right starting at (x, y)."""
        advance = (font.WIDTH + _GAP) * scale
        cx = x
        for ch in s:
            self.char(ch, cx, y, scale, color)
            cx += advance

    def text_centered(self, s: str, cx: int, cy: int, scale: int = 1) -> None:
        """Draw ``s`` centered on the point (cx, cy)."""
        x = cx - self.text_width(s, scale) // 2
        y = cy - self.text_height(scale) // 2
        self.text(s, x, y, scale)

    def _block(self, x0: int, y0: int, size: int, color: int) -> None:
        """Fill a ``size``x``size`` square of pixels at (x0, y0)."""
        for dx in range(size):
            for dy in range(size):
                self.driver.pixel(x0 + dx, y0 + dy, color)


class BouncingText:
    """A string that drifts and reflects off the canvas edges."""

    def __init__(
        self,
        canvas: OledCanvas,
        s: str,
        scale: int | None = None,
        max_scale: int | None = None,
        dx: int = 2,
        dy: int = 1,
        *,
        random_reflect: bool = False,
    ) -> None:
        """Place the text at the origin and size its travel bounds.

        Args:
            canvas: The surface it draws onto and bounces within.
            s: The string to render.
            scale: Integer scale; ``None`` auto-fits the string to the canvas.
            max_scale: Upper bound applied when auto-fitting; ignored when ``scale`` is given.
            dx: Horizontal step in pixels per ``step()``.
            dy: Vertical step in pixels per ``step()``.
            random_reflect: When ``True``, pick a new random speed magnitude (1-3)
                on each edge reflection instead of keeping the initial step sizes.
        """
        self.canvas = canvas
        self.s = s
        self._max_scale = max_scale
        self._random_reflect = random_reflect
        if scale is None:
            computed = canvas.fit_scale(s, canvas.width, canvas.height)
            self.scale = min(max_scale, computed) if max_scale else computed
        else:
            self.scale = scale
        self.x = 0
        self.y = 0
        self.dx = dx
        self.dy = dy
        # Travel bounds keep the whole glyph block on-screen; clamp to 0 so a
        # string wider/taller than the panel parks at the origin instead of
        # producing a negative range.
        self._max_x = max(0, canvas.width - canvas.text_width(s, self.scale))
        self._max_y = max(0, canvas.height - canvas.text_height(self.scale))

    def update_text(self, s: str) -> None:
        """Replace the rendered string, recompute scale and bounds, clamp position.

        Args:
            s: New string to render (e.g. an updated counter value).
        """
        self.s = s
        computed = self.canvas.fit_scale(s, self.canvas.width, self.canvas.height)
        self.scale = min(self._max_scale, computed) if self._max_scale else computed
        self._max_x = max(0, self.canvas.width - self.canvas.text_width(s, self.scale))
        self._max_y = max(0, self.canvas.height - self.canvas.text_height(self.scale))
        self.x = min(self.x, self._max_x)
        self.y = min(self.y, self._max_y)

    def step(self) -> None:
        """Advance one frame, reflecting (and clamping) at each edge."""
        self.x += self.dx
        self.y += self.dy
        if self.x <= 0:
            self.x = 0
            self.dx = random.randint(1, 3) if self._random_reflect else abs(self.dx)  # noqa: S311
        elif self.x >= self._max_x:
            self.x = self._max_x
            self.dx = -random.randint(1, 3) if self._random_reflect else -abs(self.dx)  # noqa: S311
        if self.y <= 0:
            self.y = 0
            self.dy = random.randint(1, 3) if self._random_reflect else abs(self.dy)  # noqa: S311
        elif self.y >= self._max_y:
            self.y = self._max_y
            self.dy = -random.randint(1, 3) if self._random_reflect else -abs(self.dy)  # noqa: S311

    def draw(self) -> None:
        """Render the text at its current position."""
        self.canvas.text(self.s, self.x, self.y, self.scale)
