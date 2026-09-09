# max7219

MicroPython driver for a 16x32 LED matrix built from two 8x32 MAX7219 panels
(four cascaded 8x8 FC-16 modules each) daisy-chained on one SPI bus. The caller
supplies the SPI pins, so the project owns the wiring. The driver presents the
cascade as a single 16-row x 32-column surface in human-visual coordinates
(`y = 0` is the top row of the top panel, `x = 0` the leftmost column); callers
never address individual chips.

## Public API

- `MAX7219(*, spi_id, sck, mosi, cs, brightness=1.0)` — a `pixel_display.Display`
  that opens SPI from flat project pins and drives the cascaded chain as its
  backend. It reports the chain's fixed 32x16 geometry as `width_pixels` /
  `height_pixels`; the panel wiring, not the caller, decides it.
- `display.show(frame)` — the only public render method. Build frames with
  `pixel_frame.Frame` and text content with `pixel_frame.Text`.

The package backend owns the MAX7219 cascade, the global
brightness register, and flush behavior. It writes only changed digit rows for
ordinary animation frames, writes the brightness register only when the mapped
intensity changes, and uses unchanged repeated frames to reassert chip config and
the current matrix state. `pixel_frame` owns frame construction and text
rendering; `pixel_display` owns display geometry, brightness scaling, and
failure rendering.

## Pins

Supplied by the caller from the project's `BOARD` wiring table — `spi_id`/`sck`/
`mosi` and `cs`. Each project defines its own board wiring in `main.py`; a
write-only display uses no MISO.

## Chain topology

The two panels share one SPI bus. The MCU cables to the **top** panel only
(CLK/DIN/CS); the **bottom** panel daisy-chains off the top panel's DOUT header,
which carries 5 V · GND · DOUT · CS · CLK down the chain. Only the panel-side
pins (VCC/GND/DIN/CS/CLK) are the driver's business — for a wired-up board
diagram see the [clock project README](../../projects/clock/README.md#wiring).

**Power:** the MAX7219 is a 5 V part — power both panels' VCC from the 5 V USB
rail; the daisy-chain ribbon carries 5 V / GND from the top panel to the bottom.
The MCU's 3.3 V SPI drives only the top panel's DIN / CS / CLK directly — fine at
1 MHz over short leads. Eight cascaded MAX7219s can draw well over 1 A at full
brightness, so use an external 5 V supply for sustained use.

## Hardware notes

Digit registers 1-8 drive each chip's rows; data bits drive its columns. The
framebuffer holds the image the right way up; `show()` maps it onto the chain at
the last moment: chips 0-3 are the top panel and 4-7 the bottom, and the SPI
cascade shifts the first byte to the last chip, so each frame is emitted with the
chips reversed. Digit register 0 drives a panel's bottom row, so chip rows are
emitted up each panel's visual rows. `display.flip()` rotates the whole 16x32
surface 180 degrees at runtime, for panels hung the other way up. On init the
driver briefly lights every LED via the display-test register as a wiring check.
