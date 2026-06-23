# max7219

MicroPython driver for a 16x32 LED matrix built from two 8x32 MAX7219 panels
(four cascaded 8x8 FC-16 modules each) daisy-chained on one SPI bus. The caller
supplies the SPI pins, so the project owns the wiring. The driver presents the
cascade as a single 16-row x 32-column surface in human-visual coordinates
(`y = 0` is the top row of the top panel, `x = 0` the leftmost column); callers
never address individual chips.

## Public API

- `MAX7219(*, spi_id, sck, mosi, cs, width_pixels=32, height_pixels=16,
  intensity_limit=1.0, allow_lossy=False, failure_mode="corner_xs")` — opens
  SPI from flat project pins and wraps the
  hardware backend in `pixel_display.Display`.
- `display.show(frame)` — the only public render method. Build frames with
  `pixel_display.Frame`, e.g. `Frame.text_lines(("GPS", "WAIT"))`, or
  `pixel_display.Canvas` for exact-size monochrome animation frames.

The package backend owns the MAX7219 cascade, monochrome conversion, global
brightness register, and flush behavior. It writes only changed digit rows for
ordinary animation frames, writes the brightness register only when the mapped
intensity changes, and uses unchanged repeated frames to reassert chip config and
the current matrix state. `pixel_display` owns abstract frame geometry, fitting,
intensity caps, and failure rendering.

## Pins

Supplied by the caller from the project's `BOARD` wiring table — `spi_id`/`sck`/
`mosi` and `cs`. Each project defines its own board wiring in `main.py`; a
write-only display uses no MISO.

## Wiring — RP2040-Zero example

The two panels share one SPI bus. The MCU cables to the **top** panel only
(CLK/DIN/CS); the **bottom** panel daisy-chains off the top panel's DOUT header,
which carries 5 V · GND · DOUT · CS · CLK down the chain. The GPIOs below come
from the project's `BOARD` table; the panel-side pins (VCC/GND/DIN/CS/CLK) are
what matter on any board.

### MAX7219 16x32 matrix (two 8x32 panels daisy-chained)

```
                              ┌──────────────────────────────┐
                              │  ███ 8×32 MAX7219 MATRIX ███ │  top panel — cabled to the MCU
                5V ────► VCC ─┤██████████████████████████████│
               GND ────► GND ─┤                              │
           MCU DIN ────► DIN ─┤  IN ►   FC-16 MODULE   ► OUT ├─┐
            MCU CS ────► CS  ─┤                              │ │  OUT header carries
           MCU CLK ────► CLK ─┤                              │ │  5 V · GND · DOUT · CS · CLK
                              └──────────────────────────────┘ │
                              ┌──────────────────────────────┐ │
                              │  ███ 8×32 MAX7219 MATRIX ███ │ │  bottom panel — daisy-chained
                       VCC ◄──┤██████████████████████████████│ │
                       GND ◄──┤                              │ │
                       DIN ◄──┤  IN ►   FC-16 MODULE         ├─┘  (top DOUT → bottom DIN;
                       CS  ◄──┤                              │     CS / CLK shared down chain)
                       CLK ◄──┤                              │
                              └──────────────────────────────┘
```

**Power:** the MAX7219 is a 5 V part — power both panels' VCC from the 5 V USB
rail; the daisy-chain ribbon carries 5 V / GND from the top panel to the bottom.
The MCU's 3.3 V SPI drives only the top panel's DIN / CS / CLK directly — fine at
1 MHz over short leads. Eight cascaded MAX7219s can draw well over 1 A at full
brightness, so use an external 5 V supply for sustained use.

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
    TOP MATRIX CLK ◄───── 26 ─┤        WS2812         ├─ 6  (free — bottom panel
                          15 ─┤        on GP16        ├─ 7   daisy-chains off the
                          14 ─┤                       ├─ 8   top panel's DOUT)
                              │    RP2040 BOARD       │
                              │                       │
                              └─┬────┬────┬────┬────┬─┘
```

The chain runs on SPI1 — **CLK=GP26, DIN=GP27, CS=GP28** — to the top panel; the
bottom panel takes its input from the top panel's DOUT, so it needs no MCU pins.
The on-board WS2812 is driven by GP16 — no external wiring required. Power the
panels from a 5 V supply.

## Hardware notes

Digit registers 1-8 drive each chip's rows; data bits drive its columns. The
framebuffer holds the image the right way up; `refresh` maps it onto the chain at
the last moment: chips 0-3 are the top panel and 4-7 the bottom, and the SPI
cascade shifts the first byte to the last chip, so each frame is emitted with the
chips reversed. Two orientation knobs in `max7219.py` correct the panels'
physical mounting — `_MIRROR_X` (flip if text reads backwards left-to-right) and
`_FLIP_Y` (flip if text reads upside down). On init the driver briefly lights
every LED via the display-test register as a wiring check.
