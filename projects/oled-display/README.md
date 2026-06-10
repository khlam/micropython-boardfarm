# oled-display

Drives an SSD1306 OLED over I²C: a `hello world!` banner bounces and reflects
off the panel edges while a counter, centered on the display, ticks up once per
second. The first *output* project in the boardfarm — the OLED is the display,
so there is no web dashboard.

All layout and scaling live in the chip-agnostic [`oled_canvas`](../../firmware-packages/oled_canvas)
layer over the [`ssd1306`](../../firmware-packages/ssd1306) driver, so
[firmware/main.py](firmware/main.py) holds no hard-coded pixel coordinates and
works unchanged on a 128×64 or 128×32 panel. Frame telemetry (`count`, banner
`x`/`y`) streams as JSON over USB-CDC via `emit()` for host-side debugging.

## Wiring

### SSD1306 OLED module

```
                              ┌─────────────────────┐
                              │   ┌──────────────┐  │
                              │   │  SSD1306 IC  │  │
                              │   │      ◎       │  │
                              │   └──────────────┘  │
                              │                     │
               3V3 ────► VCC ─┤                     │
               GND ────► GND ─┤   0.96" I²C OLED    │
               SCL ────► SCL ─┤                     │
               SDA ────► SDA ─┤                     │
                              │                     │
                              └─────────────────────┘
```

**Power:** most 4-pin SSD1306 breakouts run at 3.3 V directly (no onboard
regulator), so power VCC from the MCU's **3V3** pin. The SSD1306 responds at
`0x3C` by default; modules with the ADDR pad bridged answer at `0x3D` instead.

### RP2040-Zero

```
                                   ┌─── USB-C ───┐
                              ┌────┴─────────────┴────┐
                              │                       │
                          5V ─┤                       ├─ 0  ────► SSD1306 SDA
      SSD1306 GND ◄─── GND ──┤                       ├─ 1  ────► SSD1306 SCL
      SSD1306 VCC ◄─── 3V3 ──┤                       ├─ 2
                          29 ─┤                       ├─ 3
                          28 ─┤                       ├─ 4
                          27 ─┤  [BOOT] (●) [RESET]   ├─ 5
                          26 ─┤        WS2812         ├─ 6
                          15 ─┤        on GP16        ├─ 7
                          14 ─┤                       ├─ 8
                              │    RP2040 BOARD       │
                              │                       │
                              └─┬────┬────┬────┬────┬─┘
                                │    │    │    │    │
                                13   12   11   10   9
```

The on-board WS2812 sits between the BOOT and RESET buttons on the RP2040-Zero board and is driven by GP16 — no external wiring required.

### ESP32-S3-Zero

```
                                   ┌─── USB-C ───┐
                              ┌────┴─────────────┴────┐
                              │                       │
                          5V ─┤                       ├─ 13
      SSD1306 GND ◄─── GND ──┤                       ├─ 12
      SSD1306 VCC ◄─── 3V3 ──┤                       ├─ 11
      SSD1306 SDA ◄───   1 ──┤                       ├─ 10
      SSD1306 SCL ◄───   2 ──┤                       ├─ 9
                           3 ─┤  [BOOT] (●) [RESET]   ├─ 8
                           4 ─┤        WS2812         ├─ 43
                           5 ─┤        on GPIO21      ├─ 44
                           6 ─┤                       ├─ 14
                           7 ─┤   ESP32-S3-Zero       ├─ 15
                              │                       │
                              └─┬────┬────┬────┬────┬─┘
                                │    │    │    │    │
                                16   17   18   21   45
```

The on-board WS2812 is driven by GPIO21 — no external wiring required.

### RP2350

```
                                          ┌──── USB ────┐
                              ┌───────────┴─────────────┴───────────┐
                              │                                     │
      SSD1306 SDA ◄───   0 ──┤                                     ├─ VBUS
      SSD1306 SCL ◄───   1 ──┤                                     ├─ VSYS
      SSD1306 GND ◄─── GND ──┤                                     ├─ GND
                           2 ─┤                                     ├─ 3V3_EN
                           3 ─┤                                     ├─ 3V3 ────► SSD1306 VCC
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
                          15 ─┤                                     ├─ 16
                              │                                     │
                              └─────────────────────────────────────┘
```

## Build & flash
From this directory:
```
docker compose up --build pi-compile         # RP2040 + RP2350 → ./outputs/app.rp2040.rp2350.uf2
docker compose up --build esp32-compile      # ESP32-S3 → ./outputs/app.esp32-s3.bin
docker compose run --rm --build esp32-flash  # ESP32-S3 → compiles then flashes $SERIAL_PORT
```

## LED status
The boot LED follows the shared state machine: white (boot) → cyan (scanning) →
orange (no panel found) / magenta (init raised) → green (rendering) → red
(transient I²C fault).

## Tests
From the repo root:
```
docker compose up pytest --build --exit-code-from pytest -- /projects/oled-display/tests
```
Host tests AST-load `main.py` and drive `render()` with a scripted fake driver
to assert the counter cadence (once per second), the read-error recovery path,
and the JSON schema — without real hardware.
