# max7219

MicroPython driver for a cascaded MAX7219 8x8 LED-matrix chain (e.g. four
modules = one 8x32 display). The caller supplies the SPI pins, so the project
owns the wiring.

## Public API

- `connect(*, spi_id, sck, mosi, cs, num_modules=4)` — open the SPI bus on the
  given pins and return a ready `MAX7219` (the only function that touches
  `machine`). `sck`/`mosi` are the bus lines; `cs` is the display's chip-select.
- `MAX7219(spi, cs, num_modules=4)` — framebuffer driver:
  - `show_text(text)` — render text (centered, or left-aligned + clipped when it
    overflows `width`).
  - `pixel(x, y, on=True)` / `fill(on=True)` — light individual pixels or every
    LED (handy for wiring bring-up); `pixel` defers to `refresh`.
  - `clear()`, `refresh()`, `set_intensity(0..15)`, `width`.

## Pins

Supplied by the caller from the project's `BOARD` wiring table — `spi_id`/`sck`/
`mosi` and `cs` per display. Each project defines its own board wiring in
`main.py`; a write-only display uses no MISO.

## Wiring — RP2040-Zero example

The clock project drives two independent 8x32 panels on separate SPI buses that
share only the 5 V and GND rails (the GPIOs below come from its `BOARD` table;
the panel-side pins — VCC/GND/DIN/CS/CLK — are what matter on any board). Each
panel exposes a single 5-pin input header; `DOUT` is unused (write-only, and the
two panels are not daisy-chained to each other).

### MAX7219 8x32 panels

```
                              ┌──────────────────────────────┐
                              │  ███ 8×32 MAX7219 MATRIX ███ │  top panel
                              │██████████████████████████████│
                              │                              │
                5V ────► VCC ─┤                              │
               GND ────► GND ─┤                              │
           TOP DIN ────► DIN ─┤   FC-16 MODULE (DIN side)    │
            TOP CS ────► CS  ─┤                              │
           TOP CLK ────► CLK ─┤                              │
                              └──────────────────────────────┘
                              ┌──────────────────────────────┐
                              │  ███ 8×32 MAX7219 MATRIX ███ │  bottom panel
                              │██████████████████████████████│
                              │                              │
                5V ────► VCC ─┤                              │
               GND ────► GND ─┤                              │
           BOT DIN ────► DIN ─┤   FC-16 MODULE (DIN side)    │
            BOT CS ────► CS  ─┤                              │
           BOT CLK ────► CLK ─┤                              │
                              └──────────────────────────────┘
```

**Power:** the MAX7219 is a 5 V part — power each panel's VCC from the 5 V USB
rail (shared). The MCU's 3.3 V SPI drives DIN / CS / CLK directly — fine at
1 MHz over short leads. Each panel has its own SPI bus (separate CLK, DIN, CS
lines from the MCU); the DOUT connectors are unused.

### RP2040-Zero

```
                                   ┌─── USB-C ───┐
                              ┌────┴─────────────┴────┐
                              │                       │
   MATRIX VCC ◄──────── 5V ─┤                       ├─ 0
   MATRIX GND ◄─────── GND ─┤                       ├─ 1
                         3V3 ─┤                       ├─ 2
                          29 ─┤                       ├─ 3
    TOP MATRIX CS  ◄───── 28 ─┤                       ├─ 4
    TOP MATRIX DIN ◄───── 27 ─┤  [BOOT] (●) [RESET]   ├─ 5
    TOP MATRIX CLK ◄───── 26 ─┤        WS2812         ├─ 6  ────► BOT MATRIX CLK
                          15 ─┤        on GP16        ├─ 7  ────► BOT MATRIX DIN
                          14 ─┤                       ├─ 8  ────► BOT MATRIX CS
                              │    RP2040 BOARD       │
                              │                       │
                              └─┬────┬────┬────┬────┬─┘
```

The top MAX7219 runs on SPI1 — **CLK=GP26, DIN=GP27, CS=GP28**. The bottom
MAX7219 runs on SPI0 — **CLK=GP6, DIN=GP7, CS=GP8**. The on-board WS2812 is
driven by GP16 — no external wiring required. Power the panels from a 5 V
supply. The board's `5V` (USB) pad is fine for bench testing at the default mid
intensity; use an external 5 V supply for sustained full brightness, since eight
cascaded MAX7219s can draw well over 1 A.

## Hardware notes

Digit registers 1-8 drive rows; data bits drive columns. The panel is x-mirrored
(`gx = width - 1 - x`) and the SPI cascade shifts the first byte to the last
module, so `_write_row` emits modules in reverse. On init the driver briefly
lights every LED via the display-test register as a wiring check.
