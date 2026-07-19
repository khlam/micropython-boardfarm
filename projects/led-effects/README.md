# led-effects

MicroPython firmware that cycles a WS2812B addressable-LED strip through four
parametric animations — rainbow, hue rotation, breathing, and colour fade —
rendering each for 200 frames at ~50 fps before advancing to the next. A
VL53L0X time-of-flight sensor makes the strip interactive: hold an object steady
above it for 5 seconds and the strip collapses to a single LED whose position
maps the measured distance onto the bar (a live distance gauge); remove the
object for 5 seconds and a short sweep hands control back to the animations. A
128×64 SSD1306 OLED shows `Hello world` at startup. The strip driver and effects
are local to this project, and it ships no dashboard. Pin assignments live in
the firmware's `BOARD` table (dispatched per chip by `os.uname().machine`), so
the same firmware builds for RP2040, RP2350, and ESP32-S3. The sensor and OLED
are optional — either can be disconnected without stopping the animations.

## Layout
```
led-effects/
  firmware/effects.py         rainbow/hue/breathe/fade frame generators
  firmware/main.py            BOARD pin table + effect-cycling loop, calls emit()
  firmware/strip.py           project-local NeoPixel strip driver
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
- The firmware builds the four effects, then loops rendering ~200 frames of each
  (`rainbow` → `hue_rotate` → `breathe` → `color_fade`) at ~50 fps before
  advancing. It emits one JSON line per effect change (`{"effect": <name>}`) plus
  sensor diagnostics (`{"diag": "tof_ok"|"no_sensor"|"lock"|"unlock"|...}`); there
  is no dashboard.
- **The distance gauge.** Once a VL53L0X sees an object and the reading stays
  within `HOLD_TOLERANCE_MM` (25 mm) for `HOLD_MS` (5 s), the strip blanks and a
  single LED lights at the mapped position — the first LED is `MIN_DISTANCE_MM`
  (50 mm) and the last LED is `MAX_DISTANCE_MM` (500 mm, the tunable "max
  measurable distance"). Readings outside that range clamp to the nearest end.
  While locked, the lit LED tracks the object live; once the object leaves range
  for `RELEASE_MS` (5 s), `play_transition` sweeps once and the animations
  resume. All of these are constants at the top of
  [firmware/main.py](firmware/main.py) — change `MAX_DISTANCE_MM` to rescale the
  gauge.
- **The OLED.** A 128×64 I²C SSD1306 at address `0x3C` is cleared during
  startup, receives `Hello world` at the top-left, and keeps that framebuffer
  visible while the LED loop runs. Initialisation is retried three times; if the
  display remains absent or faulty, an `oled_disabled` diagnostic is emitted
  and the rest of the firmware continues.
- The strip is fixed at 20 LEDs (`LED_COUNT` in [firmware/main.py](firmware/main.py));
  change it there and recompile to drive a longer strip.
- Pins are project wiring — they live in the `BOARD` table in
  [firmware/main.py](firmware/main.py), dispatched per chip by
  `os.uname().machine`. The data pin reaches the strip as `Strip(count, pin=...)`;
  the I²C pins reach the sensor as `VL53L0X(sda=, scl=)`, which opens its own
  bit-banged soft-I²C bus internally. The SSD1306 driver opens a separate
  software-I²C bus on the OLED pins.

  | Board         | Strip data | VL53 SDA | VL53 SCL | OLED SDA | OLED SCL |
  | ------------- | ---------- | -------- | -------- | -------- | -------- |
  | RP2040-Zero   | `GP15`     | `GP0`    | `GP1`    | `GP2`    | `GP3`    |
  | RP2350        | `GP15`     | `GP0`    | `GP1`    | `GP2`    | `GP3`    |
  | ESP32-S3-Zero | `GPIO7`    | `GPIO1`  | `GPIO2`  | `GPIO8`  | `GPIO9`  |

  Every board drives the strip from a dedicated GPIO, separate from its on-board
  status indicator. RP2040-Zero and ESP32-S3-Zero use WS2812 LEDs on `GP16` and
  `GPIO21`; RP2350 uses a single-colour LED through CYW43 `WL_GPIO0`. None is
  wired into the strip chain or counted among the effects LEDs.
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

The VL53L0X breakout and four-pin SSD1306 module use separate **SDA** and
**SCL** pairs but share **3V3** and **GND**. Both are optional: leave either one
off and the animations still run. Power both from the board's 3.3 V rail:

| Peripheral pin | RP2040-Zero | RP2350 | ESP32-S3-Zero |
| -------------- | ----------- | ------ | ------------- |
| OLED VCC        | `3V3`       | `3V3`  | `3V3`         |
| OLED GND        | `GND`       | `GND`  | `GND`         |
| OLED SDA        | `GP2`       | `GP2`  | `GPIO8`       |
| OLED SCL        | `GP3`       | `GP3`  | `GPIO9`       |

| VL53L0X pin | RP2040-Zero | RP2350 | ESP32-S3-Zero |
| ----------- | ----------- | ------ | ------------- |
| VIN         | `3V3`       | `3V3`  | `3V3`         |
| GND         | `GND`       | `GND`  | `GND`         |
| SDA         | `GP0`       | `GP0`  | `GPIO1`       |
| SCL         | `GP1`       | `GP1`  | `GPIO2`       |

> ⚠️ **Power both I²C modules from `3V3`, not the 5V strip rail.** These MCUs'
> GPIOs are not 5V-tolerant, and typical breakouts pull their I²C lines up to
> their supply. A 5 V supply can therefore idle SDA/SCL at 5 V and damage the
> board. Share a common GND across the board, strip, sensor, and OLED.

### RP2040-Zero

```
                                   ┌─── USB-C ───┐
                              ┌────┴─────────────┴────┐
                              │                       │
         WS2812B 5V ◄───  5V ─┤                       ├─ 0 ───► VL53L0X SDA
 OLED/VL53/STRIP GND ◄── GND ─┤                       ├─ 1 ───► VL53L0X SCL
      OLED/VL53 VCC ◄─── 3V3 ─┤                       ├─ 2 ───► OLED SDA
                          29 ─┤                       ├─ 3 ───► OLED SCL
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

The strip's `DIN` goes to `GP15`, leaving the on-board WS2812 (boot status LED)
on `GP16` free. The VL53L0X uses `GP0`/`GP1`; the OLED uses `GP2`/`GP3`.
They share `3V3` and GND.

### ESP32-S3-Zero

```
                                    ┌───── USB-C ─────┐
                               ┌────┴─────────────────┴────┐
     WS2812B 5V ◄── 5V / VBUS ─┤                           ├─ GPIO43 / TX
  OLED/VL53/STRIP GND ◄── GND ─┤                           ├─ GPIO44 / RX
     OLED/VL53 VCC ◄─ 3V3 OUT ─┤                           ├─ GPIO13
        VL53L0X SDA ◄── GPIO1 ─┤                           ├─ GPIO12
        VL53L0X SCL ◄── GPIO2 ─┤                           ├─ GPIO11
                        GPIO3 ─┤   [BOOT]       [RESET]    ├─ GPIO10
                        GPIO4 ─┤    GPIO0          EN      ├─ GPIO9 ───► OLED SCL
                        GPIO5 ─┤                           ├─ GPIO8 ───► OLED SDA
                        GPIO6 ─┤    WS2812: GPIO21         ├─ GPIO7 ───► WS2812B DIN
                               │                           │
                               └───────────────────────────┘
```

The strip's `DIN` goes to `GPIO7`, leaving the on-board WS2812 (boot status LED)
on `GPIO21` free — the on-board pixel is never part of the strip chain. The
VL53L0X uses `GPIO1`/`GPIO2`; the OLED uses `GPIO8`/`GPIO9`. They share `3V3`
and GND.

### RP2350

```
                                          ┌──── USB ────┐
                              ┌───────────┴─────────────┴───────────┐
                              │                                     │
        VL53L0X SDA ◄───   0 ─┤                                     ├─ VBUS ────► WS2812B 5V
        VL53L0X SCL ◄───   1 ─┤                                     ├─ VSYS
        WS2812B GND ◄─── GND ─┤                                     ├─ GND
           OLED SDA ◄───   2 ─┤                                     ├─ 3V3_EN
           OLED SCL ◄───   3 ─┤                                     ├─ 3V3 ────► I²C VCC
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

`VBUS` is the 5 V USB rail. The strip's `DIN` goes to `GP15`, separate from the
single-colour boot status LED on CYW43 `WL_GPIO0`. The VL53L0X uses `GP0`/`GP1`;
the OLED uses `GP2`/`GP3`. They share `3V3` and GND.

**Power**
- A WS2812B LED draws up to ~60 mA at full white. A handful of LEDs can run from
  the board's `5V`/`VBUS` pin over USB; for longer strips feed the strip from a
  dedicated 5V supply and still tie all grounds together.
- These boards drive `DIN` at 3.3 V logic, which is reliable for short leads. For
  long runs, add a 5V level shifter on the data line.
- Power the VL53L0X and OLED from the board's `3V3` pin, **not** the 5V strip
  rail: the GPIOs are not 5V-tolerant and breakout I²C pull-ups commonly sit on
  their supply rail. Their `GND` pins tie into the strip's common ground.
