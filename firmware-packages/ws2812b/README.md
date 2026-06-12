# ws2812b

Chip-dispatched WS2812B addressable-LED strip driver plus a small set of
parametric animation effects. The effect maths is pure (host-testable under
CPython); the only chip-specific detail — the strip's data GPIO — lives in the
per-chip backends (`rp2040`, `rp2350`, `esp32s3`) selected at import time, the
same pattern `boot_status_led` uses.

## Effects

| Effect | What it does | Tuning parameters |
| --- | --- | --- |
| `Rainbow` | Full spectrum laid across the strip, scrolling | `count`, `brightness`, `step` |
| `HueRotate` | All LEDs share one hue that rotates over time | `count`, `brightness`, `speed` |
| `Breathe` | Sinusoidal brightness pulse of one colour | `count`, `color`, `brightness`, `period` |
| `ColorFade` | Ping-pong interpolation between two colours | `count`, `start`, `end`, `brightness`, `step` |

Every animation parameter is a constructor argument with a sensible default —
there are no hardcoded magic numbers in the effect bodies, only the fixed
constants of the 8-bit RGB / HSV colour model.

## Usage

```python
from ws2812b import Strip, Rainbow

strip = Strip(8)                                   # 8 LEDs on the board's data pin
effect = Rainbow(8, brightness=0.3, step=0.01)
while True:
    strip.render(effect.frame())                   # one frame per render
    time.sleep_ms(20)
```

`Strip.render(frame)` writes a list of `(r, g, b)` tuples (one per LED, as
produced by an effect's `frame()`) and latches them to the strip.
