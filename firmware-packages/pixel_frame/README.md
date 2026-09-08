# pixel_frame

Frame construction and text rendering for MicroPython pixel displays.

`pixel_frame` owns rendering logic: packed frame bytes, text glyphs, glyph
measurement, and pixel-box placement. Display packages consume the resulting
frames through `display.show(frame)` and do not know about fonts or layout.

```python
from pixel_frame import Frame, Text

frame = Frame(width=32, height=16)
frame[0:8, 0:32] = Text("12:05 PM")
frame[8:16, 0:32] = Text("TUE 23")
display.show(frame)
```

Slice assignment uses matrix order: `frame[y_slice, x_slice]`.

## Public API

- `Frame(width, height, intensity=255, *, stride=None, data=None)` creates an
  exact-size packed monochrome frame, or wraps packed `data` produced by
  transition or backend helpers.
- `Text(value, scale=None, align="center", valign="middle",
  hidden_chars="")` describes text for a frame box.

`Text` chooses the largest integer scale that fits the assigned box unless an
explicit `(x, y)` scale pair is provided. Adjacent visible characters always reserve at least
one blank pixel column between them. Characters listed in `hidden_chars`
reserve their normal advance but draw no pixels, so blink states do not shift
layout.

Firmware can choose alternate wording before drawing:

```python
width = display.width_pixels
row_height = display.height_pixels // 2
label = f"{full_month} {day}"
if not Text(label).fits(width, row_height):
    label = f"{month_abbr} {day}"
frame[0:row_height, 0:width] = Text(label)
```
