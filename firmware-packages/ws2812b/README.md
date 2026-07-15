# ws2812b

WS2812B addressable-LED strip driver plus a small set of parametric animation
effects. The effect maths is pure (host-testable under CPython); the strip's
data GPIO is project wiring, supplied by the caller from the project's BOARD
table (`Strip(count, pin=...)`), so the package holds no per-chip
configuration.

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

strip = Strip(8, pin=15)                           # 8 LEDs, DIN on GPIO15
effect = Rainbow(8, brightness=0.3, step=0.01)
while True:
    strip.render(effect.frame())                   # one frame per render
    time.sleep_ms(20)
```

`Strip.render(frame)` writes a list of `(r, g, b)` tuples (one per LED, as
produced by an effect's `frame()`) and latches them to the strip.
