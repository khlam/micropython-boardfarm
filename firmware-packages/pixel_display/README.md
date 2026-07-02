# pixel_display

Hardware-agnostic display facade for MicroPython pixel outputs.

`pixel_display` owns display policy only: declared geometry, normalized
brightness, failure rendering, frame fitting, and the backend write contract.
Frame construction and text rendering live in [`pixel_frame`](../pixel_frame/).

```python
from pixel_display import Display
from pixel_frame import Frame, Text

frame = Frame(width=32, height=16)
frame[0:8, 0:32] = Text("GPS")
frame[8:16, 0:32] = Text("WAIT")

display.show(frame)
```

`Display` scales and centers frames into `width_pixels` × `height_pixels`,
applies normalized brightness, then calls a backend:

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
