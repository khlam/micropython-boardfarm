# oled_canvas

A higher-level layout layer for monochrome panels. It takes the panel's
**width and height as constructor parameters** and owns all geometry —
text rendering from a bundled 5×8 font, integer up-scaling, measurement,
auto-fit, and centering — so callers describe *what* to draw and never
hard-code pixel coordinates that assume a fixed panel size.

Driver-agnostic: it wraps any object exposing `pixel(x, y, c)` / `fill(c)` /
`show()` (the object is passed in, not imported), so it composes with the
[`ssd1306`](../ssd1306) driver without depending on it.

## Layout
```
oled_canvas/
  oled_canvas/
    __init__.py      re-exports OledCanvas, BouncingText
    oled_canvas.py   the layout layer
    font.py          vendored public-domain 5×8 ASCII font (see VENDOR.md)
  tests/             host pytest against an in-memory fake driver
```

## Public API
```python
from ssd1306 import SSD1306
from oled_canvas import OledCanvas, BouncingText

oled = SSD1306(i2c, 128, 64)
canvas = OledCanvas(oled, 128, 64)

canvas.clear()
canvas.text("hello", 0, 0, scale=2)                 # top-left at (x, y)
canvas.text_centered("42", 64, 32, scale=3)          # centered on a point
scale = canvas.fit_scale("hello", 128, 64)           # largest scale that fits
canvas.show()

banner = BouncingText(canvas, "hello world!")        # auto-scales to fit
banner.step()                                        # move + reflect off edges
banner.draw()
```

## Notes
- `text_width` / `text_height` measure advance dimensions (including the
  1-pixel inter-glyph gap), in the same units `fit_scale` and `text_centered`
  use internally.
- `fit_scale` never returns below 1: an over-long string is drawn at scale 1
  and clipped rather than vanishing.
- The font is column-major with bit 0 at the top — the same layout as the
  SSD1306 MONO_VLSB framebuffer — so a scaled glyph pixel is a plain bit test.

## Tests
From the repo root:
```
docker compose up pytest --build --exit-code-from pytest -- /firmware-packages/oled_canvas/tests
```
`tests/fake_driver.py` records lit pixels as a set, so tests assert exact
rendered geometry: measurement arithmetic, auto-fit selection, glyph blitting
(with up-scaling and clearing), centering, and the edge-reflecting sprite.
