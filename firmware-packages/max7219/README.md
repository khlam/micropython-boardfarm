# max7219

MicroPython driver for a 4-module (8x32) MAX7219 LED matrix, plus fonts and a
clock display-cycle. Chip-specific SPI pins live in per-chip backends, so callers
stay board-agnostic.

## Public API

- `connect()` — open this chip's SPI bus and return a ready `MAX7219` (the only
  function that touches `machine`).
- `MAX7219(spi, cs)` — framebuffer driver: `show_text`, `show_auto`, `show_time`,
  `set_text`, `scroll_step`, `wiggle_step`, `set_intensity`, `clear`, `refresh`.
- `DisplayCycle(display, rtc)` — alternates a TIME phase (bold 12-hour digits,
  blinking colon, AM/PM) and a DAY phase (weekday name) reading a `machine.RTC`.
- `format_time_12h(hour24, minute, colon_on)` / `day_name(weekday)` — pure
  formatting helpers (host-testable without hardware).

## Pins

| Chip | SCK | MOSI/DIN | CS |
| --- | --- | --- | --- |
| RP2040 | GP18 | GP19 | GP17 |
| RP2350 | GP18 | GP19 | GP17 |
| ESP32-S3 | GPIO12 | GPIO11 | GPIO10 |

All are disjoint from the ATGM336H GPS UART pins, so display SPI and GPS UART run
concurrently without contention.

## Hardware notes

Digit registers 1-8 drive rows; data bits drive columns. The panel is x-mirrored
(`gx = 31 - x`) and the SPI cascade shifts the first byte to the last module, so
`_write_row` emits modules in reverse. Ported from a standalone RP2350 project.
