# pixel_display

Hardware-agnostic frame and display facade for MicroPython pixel outputs.

Public API:

```python
from pixel_display import Canvas, Display, Frame

display.show(Frame.text_lines(("GPS", "WAIT")))

canvas = Canvas(32, 16)
canvas.pixel(0, 0)
display.show(canvas.frame())
```

`Frame` stores row-major pixel data as `bytearray` plus explicit
`width`/`height`/`channels`. Helper constructors accept normalized intensities
from `0.0` to `1.0` and quantize them to bytes:

- `Frame.from_matrix(matrix)` for 2D intensity or channel matrices.
- `Frame.text(text)`, `Frame.number(value)`, `Frame.text_lines(lines)`.
- `Frame.blank(width, height, channels=1)`.

`Canvas` builds `PackedFrame` objects for monochrome displays. A packed frame
stores one bit per pixel plus one shared byte intensity, so exact-size
monochrome animations can avoid allocating and scaling a full byte per pixel on
every refresh.

`Display` owns geometry fit, normalized brightness caps, and failure rendering.
It scales and centers frames into `width_pixels` × `height_pixels`, applies the
configured intensity cap, then calls a backend:

```python
backend.write_frame(frame, allow_lossy=False)
backend.clear()
```

Backends own everything hardware-specific: buses, flush timing, monochrome or RGB
conversion, LED order, panel wiring, and any model-specific layout.

## Adapter Pattern

Hardware packages should expose a flat constructor that opens its own bus, builds
its private backend, and wraps it in `Display`. For example, an SSD1306/OLED
adapter should accept `bus_id`/`sda`/`scl`/`width_pixels`/`height_pixels`, scan or
init the panel in the SSD1306 package, and convert the fitted one-channel frame
to the panel framebuffer in `write_frame`.

A WS2812B adapter should accept the data pin and declared geometry, then map the
fitted frame pixels to LED indexes inside its backend. RGB ordering, strip order,
serpentine grids, chains, and the final `NeoPixel.write()` stay there, not in
`pixel_display`.

If a backend cannot represent a frame exactly, it returns `False` unless
`allow_lossy=True`; the facade then shows the configured failure indicator.
