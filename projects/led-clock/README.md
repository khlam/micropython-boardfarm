# led-clock

MicroPython firmware for an LED clock made of WS2812B addressable LEDs chained
from a single data pin. One digit is connected today: a seven-segment display
with 2 LEDs per segment, 14 LEDs in all. On boot the digit counts 0 to 9 in
green, one step per second, and repeats. There is no dashboard.

RP2040-Zero is the only supported board.

## Layout
```
led-clock/
  firmware/main.py            wiring constants + count loop, calls emit()
  firmware/seven_segment.py   digit → per-LED frame (no hardware dependency)
  tests/                      host pytest
  outputs/                    build artifact (RP2040-only UF2)
  docker-compose.yaml         rp2040-compile service
```

## Usage

1. Compile the firmware:
   ```bash
   docker compose up --build rp2040-compile
   ```
   This writes [outputs/app.rp2040.uf2](outputs/app.rp2040.uf2), an RP2040-only
   UF2. Unlike the other projects' universal `app.rp2040.rp2350.uf2`, it has no
   RP2350 half. The RP2040 bootloader reboots as soon as it has its own blocks,
   so with the universal file the copy fails partway even though the flash
   worked.
2. Put the board in [bootloader mode](../microcontrollers.md#bootloader-mode).
3. Drag-and-drop the UF2 onto the `RPI-RP2` drive. The board ejects and reboots
   running the new firmware.

Tests run from the repo root:
```bash
docker compose run --rm --build pytest /projects/led-clock/tests
```

## Notes
- Each step prints one JSON line on the USB serial port, `{"digit": <0-9>}`.
- The on-board WS2812 on `GP16` shows boot status: white at boot, green once
  counting. See the [Boot LED states table](../../firmware-packages/boot_status_led/README.md#boot-led-states).
  It is not part of the digit's chain.
- All wiring and look settings are constants in [firmware/main.py](firmware/main.py):

  | Constant | Value | Meaning |
  |---|---|---|
  | `BOARD.data_pin` | `15` | GPIO driving the chain's `DIN` |
  | `CHAIN_ORDER` | `"abcdefg"` | Segments in the order the chain visits them, from `DIN`, using the [segment map](#segment-map) letters |
  | `LEDS_PER_SEGMENT` | `2` | LEDs wired in series within each segment |
  | `GREEN` | `(0, 64, 0)` | Lit-segment colour, about 25% brightness |
  | `STEP_PERIOD_MS` | `1000` | Time each digit is shown |

  If a segment lights in the wrong place, the chain order differs from
  `CHAIN_ORDER`. Edit that string and run `rp2040-compile` again.

## Segment map

Segment letters follow this board's own labels, not the common a-is-top
convention. `CHAIN_ORDER` and the digit shapes in
[firmware/seven_segment.py](firmware/seven_segment.py) use the same letters.
The chain `a b c d e f g` enters at the upper right, runs counterclockwise
round the outside, and ends on the middle. Each segment shows the LED indices
it owns:

```
          b: 2,3
        ┌───────┐
        │       │
 c: 4,5 │       │ a: 0,1   ◄── DIN enters at a
        │       │
        ├───────┤ g: 12,13
        │       │
 d: 6,7 │       │ f: 10,11
        │       │
        └───────┘
          e: 8,9
```

## Wiring

The chain needs three connections: **5V** (VCC), **GND**, and **DIN** (serial
data in) on the first LED. Board `GND`, chain `GND`, and any external 5V supply
must share a ground.

### RP2040-Zero

```
                                   ┌─── USB-C ───┐
                              ┌────┴─────────────┴────┐
                              │                       │
           Chain 5V ◄───  5V ─┤                       ├─ 0
          Chain GND ◄─── GND ─┤                       ├─ 1
                         3V3 ─┤                       ├─ 2
                          29 ─┤                       ├─ 3
                          28 ─┤                       ├─ 4
                          27 ─┤  [BOOT] (●) [RESET]   ├─ 5
                          26 ─┤        WS2812         ├─ 6
          Chain DIN ◄───  15 ─┤        on GP16        ├─ 7
                          14 ─┤                       ├─ 8
                              │    RP2040 BOARD       │
                              │                       │
                              └─┬────┬────┬────┬────┬─┘
                                │    │    │    │    │
                                13   12   11   10   9
```

**Power**
- A WS2812B LED draws up to ~60 mA at full white. At the default green
  (one channel at 64/255), all 14 LEDs together draw roughly 80 mA, so the
  board's `5V` pin over USB is enough.
- The board drives `DIN` at 3.3 V logic, which is reliable for short leads. For
  long runs, add a 5V level shifter on the data line.
