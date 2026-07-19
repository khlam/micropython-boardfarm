# ssd1306

MicroPython framebuffer driver for SSD1306 monochrome OLED displays over I²C.
The driver takes flat GPIO pin numbers, opens its own software-I²C bus through
`i2c_bus`, scans for the configured address, and exposes the standard
`framebuf.FrameBuffer` drawing methods.

## Public API

```python
from ssd1306 import SSD1306

display = SSD1306(sda=0, scl=1, width=128, height=64)
display.fill(0)
display.text("Hello world", 0, 0, 1)
display.show()
```

The default address is `0x3C` and the default power mode uses the SSD1306's
internal charge pump. `DeviceNotFoundError` is re-exported from this package so
project firmware can distinguish a missing display from an I²C transaction
failure.

## Tests

Run the host tests from the repository root:

```bash
docker compose run --rm --build pytest /firmware-packages/ssd1306/tests
```
