# SSD1306 driver provenance

The controller command sequence and framebuffer protocol are adapted from the
MicroPython SSD1306 driver and documentation:

- https://github.com/micropython/micropython-lib
- https://docs.micropython.org/en/v1.25.0/esp8266/tutorial/ssd1306.html

MicroPython is copyright its contributors and distributed under the MIT
License, reproduced in [LICENSE](LICENSE). The repository-facing implementation
adds flat-pin bus construction, device detection, documentation, and tests
while retaining that license.
