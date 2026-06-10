# ssd1306

MicroPython register-level driver for the SSD1306 monochrome OLED over I²C.

Chip-agnostic with respect to the MCU: it takes a `machine.I2C`/`SoftI2C`
instance from the caller and never imports `machine` itself. The panel
dimensions are constructor parameters, so the same driver covers 128×64 and
128×32 panels — the COM-pin and multiplex configuration is derived from
`height`.

The driver owns a single MONO_VLSB framebuffer and does **not** subclass
`framebuf`, so it has no native-module dependency and runs unchanged on the
host test stub. For higher-level text/layout, compose it with the
[`oled_canvas`](../oled_canvas) package.

## Layout
```
ssd1306/
  ssd1306/
    __init__.py     re-exports SSD1306
    ssd1306.py      the driver
  tests/            host pytest against a register-level simulator
```

## Public API
```python
from machine import I2C, Pin
from ssd1306 import SSD1306

i2c = I2C(0, sda=Pin(0), scl=Pin(1))
oled = SSD1306(i2c, 128, 64, addr=0x3C)   # 0x3D on some modules

oled.fill(0)            # clear the framebuffer (0 = off, non-zero = on)
oled.pixel(10, 20, 1)   # set one pixel; out-of-bounds is a silent no-op
oled.show()             # flush the framebuffer to the panel over I²C
```

## Notes
Every transfer is framed as `writeto_mem(addr, control, payload)` where the
SSD1306 control byte is `0x00` for a command stream and `0x40` for GDDRAM
data — exactly the byte the I²C peripheral emits right after the address. This
keeps the driver host-testable through the shared `machine` stub, which
implements only the `*_mem` I²C methods.

## Tests
From the repo root:
```
docker compose up pytest --build --exit-code-from pytest -- /firmware-packages/ssd1306/tests
```
A register-level fake (`tests/fake_ssd1306.py`) records the command log and
GDDRAM writes through the stubbed I²C bus. Coverage is logic-only: the
geometry-dependent init sequence, MONO_VLSB pixel addressing, bulk fills,
out-of-bounds clamping, and the address-window framing in `show()`.

## References
- [Adafruit SSD1306 datasheet](https://cdn-shop.adafruit.com/datasheets/SSD1306.pdf)
- [micropython/micropython ssd1306 driver](https://github.com/micropython/micropython-lib/blob/master/micropython/drivers/display/ssd1306/ssd1306.py)
