# led-effects

MicroPython firmware that cycles a WS2812B addressable-LED strip through four
parametric animations — rainbow, hue rotation, breathing, and colour fade —
rendering each for 200 frames at ~50 fps before advancing to the next. It is a
hardware demo for the [`ws2812b`](../../firmware-packages/ws2812b) package and
ships no dashboard; the strip's data pin is the only chip-specific detail and
lives in the backend selected at import time, so the same firmware builds for
RP2040, RP2350, and ESP32-S3.

## Layout
```
led-effects/
  firmware/main.py            chip-agnostic effect-cycling loop, calls emit()
  outputs/                    build artifacts (UF2 + ESP32 bin)
  docker-compose.yaml         pi-compile / esp32-compile / esp32-flash services
```

## Usage

### RP2040 / RP2350
1. Compile the firmware:
   ```bash
   docker compose up --build pi-compile
   ```
   A single Docker build compiles MicroPython for both boards and merges the UF2 outputs into one universal file at [outputs/app.rp2040.rp2350.uf2](outputs/app.rp2040.rp2350.uf2) that flashes correctly on either device.
2. Put the board in [bootloader mode](../microcontrollers.md#bootloader-mode).
3. Drag-and-drop [outputs/app.rp2040.rp2350.uf2](outputs/app.rp2040.rp2350.uf2) onto the mounted USB drive. The board ejects and reboots running the new firmware.

### ESP32-S3
1. Put the board in [bootloader mode](../microcontrollers.md#bootloader-mode) — the service fails fast if `/dev/ttyACM0` isn't present.
2. Compile and flash:
   ```bash
   docker compose run --rm --build esp32-flash
   ```
   Runs `esp32-compile` to produce [outputs/app.esp32-s3.bin](outputs/app.esp32-s3.bin), then immediately flashes it via `esptool.py` running inside the container.

## Notes
- The firmware builds the four effects, then loops forever rendering 200 frames
  of each (`rainbow` → `hue_rotate` → `breathe` → `color_fade`) at ~50 fps
  before advancing. It emits one JSON line per effect change
  (`{"effect": <name>}`); there is no sensor and no dashboard.
- The strip is fixed at 8 LEDs (`LED_COUNT` in [firmware/main.py](firmware/main.py));
  change it there and recompile to drive a longer strip.
- The data pin is the only chip-specific detail — it lives in `DATA_PIN` in each
  `ws2812b` backend, never in the firmware:

  | Board         | Data pin | Backend                                                                    |
  | ------------- | -------- | -------------------------------------------------------------------------- |
  | RP2040-Zero   | `GP15`   | [`ws2812b/rp2040.py`](../../firmware-packages/ws2812b/ws2812b/rp2040.py)    |
  | RP2350-Zero   | `GP15`   | [`ws2812b/rp2350.py`](../../firmware-packages/ws2812b/ws2812b/rp2350.py)    |
  | ESP32-S3-Zero | `GPIO15` | [`ws2812b/esp32s3.py`](../../firmware-packages/ws2812b/ws2812b/esp32s3.py)  |

  Every board drives the strip from a dedicated GPIO, separate from the on-board
  WS2812 (the boot status LED on `GP16` / `GPIO21`). The on-board pixel is never
  wired into the strip chain — it stays a standalone status indicator and is
  never the first LED of the effects strip.
- LED indication is chip-aware — see the [Boot LED states table](../../firmware-packages/boot_status_led/README.md#boot-led-states)
  in the boot_status_led README.

## Hardware

| RP2040-Zero board | RP2350 | ESP32-S3-Zero |
|:---:|:---:|:---:|
| <img src="../../images/rp2040-zero.jpg" alt="RP2040-Zero board" width="220"> | <img src="../../images/rp2350.jpg" alt="RP2350" width="220"> | <img src="../../images/esp32-s3.jpg" alt="ESP32-S3-Zero" width="220"> |

## Wiring

A WS2812B strip needs three connections — **5V** (VCC), **GND**, and **DIN**
(serial data in). Wire `DIN` to the input end of the strip; the arrows printed on
the strip point *away* from it. Common ground is mandatory: board `GND`, strip
`GND`, and any external 5V supply must share a ground or the data line has no
reference and the strip flickers or stays dark.

### RP2040-Zero

```
                                   ┌─── USB-C ───┐
                              ┌────┴─────────────┴────┐
                              │                       │
         WS2812B 5V ◄───  5V ─┤                       ├─ 0
        WS2812B GND ◄─── GND ─┤                       ├─ 1
                         3V3 ─┤                       ├─ 2
                          29 ─┤                       ├─ 3
                          28 ─┤                       ├─ 4
                          27 ─┤  [BOOT] (●) [RESET]   ├─ 5
                          26 ─┤        WS2812         ├─ 6
        WS2812B DIN ◄───  15 ─┤        on GP16        ├─ 7
                          14 ─┤                       ├─ 8
                              │    RP2040 BOARD       │
                              │                       │
                              └─┬────┬────┬────┬────┬─┘
                                │    │    │    │    │
                                13   12   11   10   9
```

The strip's `DIN` goes to `GP15`, leaving the on-board WS2812 (boot status LED) on `GP16` free.

### ESP32-S3-Zero

```
                                   ┌─── USB-C ───┐
                              ┌────┴─────────────┴────┐
                              │                       │
         WS2812B 5V ◄───  5V ─┤                       ├─ 13
        WS2812B GND ◄─── GND ─┤                       ├─ 12
                         3V3 ─┤                       ├─ 11
                           1 ─┤                       ├─ 10
                           2 ─┤                       ├─ 9
                           3 ─┤  [BOOT] (●) [RESET]   ├─ 8
                           4 ─┤        WS2812         ├─ 43
                           5 ─┤        on GPIO21      ├─ 44
                           6 ─┤                       ├─ 14
                           7 ─┤   ESP32-S3-Zero       ├─ 15 ────► WS2812B DIN
                              │                       │
                              └─┬────┬────┬────┬────┬─┘
                                │    │    │    │    │
                                16   17   18   21   45
```

The strip's `DIN` goes to `GPIO15`, leaving the on-board WS2812 (boot status LED) on `GPIO21` free — the on-board pixel is never part of the strip chain.

### RP2350

```
                                          ┌──── USB ────┐
                              ┌───────────┴─────────────┴───────────┐
                              │                                     │
                           0 ─┤                                     ├─ VBUS ────► WS2812B 5V
                           1 ─┤                                     ├─ VSYS
        WS2812B GND ◄─── GND ─┤                                     ├─ GND
                           2 ─┤                                     ├─ 3V3_EN
                           3 ─┤                                     ├─ 3V3
                           4 ─┤                                     ├─ ADC_VREF
                           5 ─┤                                     ├─ 28
                         GND ─┤   [BOOTSEL] (●) LED on WL_GPIO0     ├─ AGND
                           6 ─┤                                     ├─ 27
                           7 ─┤                                     ├─ 26
                           8 ─┤      RP2350                         ├─ RUN
                           9 ─┤                                     ├─ 22
                         GND ─┤                                     ├─ GND
                          10 ─┤                                     ├─ 21
                          11 ─┤                                     ├─ 20
                          12 ─┤                                     ├─ 19
                          13 ─┤                                     ├─ 18
                         GND ─┤                                     ├─ GND
                          14 ─┤                                     ├─ 17
        WS2812B DIN ◄───  15 ─┤                                     ├─ 16
                              │                                     │
                              └─────────────────────────────────────┘
```

`VBUS` is the 5 V USB rail. The strip's `DIN` goes to `GP15`, leaving the on-board WS2812 (boot status LED) on `GP16` free — the on-board pixel is never part of the strip chain.

**Power**
- A WS2812B LED draws up to ~60 mA at full white. A handful of LEDs can run from
  the board's `5V`/`VBUS` pin over USB; for longer strips feed the strip from a
  dedicated 5V supply and still tie all grounds together.
- These boards drive `DIN` at 3.3 V logic, which is reliable for short leads. For
  long runs, add a 5V level shifter on the data line.
