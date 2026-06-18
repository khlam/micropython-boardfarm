# max7219

MicroPython driver for a 4-module (8x32) MAX7219 LED matrix, plus fonts and a
clock display-cycle. The caller supplies the SPI pins, so the project owns the
wiring (see [`board_pinout`](../board_pinout/README.md)).

## Public API

- `connect(*, spi_id, sck, mosi, cs)` — open the SPI bus on the given pins and
  return a ready `MAX7219` (the only function that touches `machine`). `sck`/`mosi`
  are the shared bus lines; `cs` is the display device's chip-select.
- `MAX7219(spi, cs)` — framebuffer driver: `show_text`, `show_auto`, `show_time`,
  `set_text`, `scroll_step`, `wiggle_step`, `set_intensity`, `clear`, `refresh`.
- `DisplayCycle(display, rtc)` — alternates a TIME phase (bold 12-hour digits,
  blinking colon, AM/PM) and a DAY phase (weekday name) reading a `machine.RTC`.
- `format_time_12h(hour24, minute, colon_on)` / `day_name(weekday)` — pure
  formatting helpers (host-testable without hardware).

## Pins

Supplied by the caller from `board_pinout.BOARD` — `spi_id`/`sck`/`mosi` from the
shared `BOARD.spi` bus and `cs` from `BOARD.devices["display"]`. The wiring per
board is documented in [`board_pinout`](../board_pinout/README.md); a write-only
display uses no MISO.

## Hardware notes

Digit registers 1-8 drive rows; data bits drive columns. The panel is x-mirrored
(`gx = 31 - x`) and the SPI cascade shifts the first byte to the last module, so
`_write_row` emits modules in reverse. Ported from a standalone RP2350 project.
