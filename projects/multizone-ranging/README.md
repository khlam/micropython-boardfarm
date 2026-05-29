# multizone-ranging

MicroPython firmware that reads a VL53L5CX 8×8 multizone time-of-flight
sensor and streams distance grids as JSON lines over USB-CDC at ~10 Hz.
A host FastAPI service serves a live Plotly heatmap dashboard.

## Layout
```
multizone-ranging/
  firmware/main.py            chip-agnostic streaming loop, calls emit()
  viz/static/index.html       Plotly 8×8 heatmap + distance stats
  tests/                      host pytest for the emit() schema
  outputs/                    build artifacts (UF2 + ESP32 bin)
  docker-compose.yaml         compile / esp32 / viz services
```

## Usage

### RP2040 / RP2350
1. Build the firmware:
   ```bash
   docker compose up --build compile
   ```
   A single Docker build compiles MicroPython for both boards and merges the UF2 outputs into one universal file at [outputs/app.rp2040.rp2350.uf2](outputs/app.rp2040.rp2350.uf2) that flashes correctly on either device.
2. Put the board in [bootloader mode](../../README.md#bootloader-mode).
3. Drag-and-drop [outputs/app.rp2040.rp2350.uf2](outputs/app.rp2040.rp2350.uf2) onto the mounted USB drive. The board ejects and reboots running the new firmware.

### ESP32-S3
1. Put the board in [bootloader mode](../../README.md#bootloader-mode) — the service fails fast if `/dev/ttyACM0` isn't present.
2. Build and flash:
   ```bash
   docker compose run --rm --build esp32
   ```
   Builds [outputs/app.esp32-s3.bin](outputs/app.esp32-s3.bin) and immediately flashes it via `esptool.py` running inside the container.

### Web dashboard
With the board plugged in (`/dev/ttyACM0`):
```bash
docker compose up --build viz
```
Open `http://localhost:18501`. The connection pill turns green when the
serial port is open, and the 8×8 heatmap and distance stats update in
real time.

## Notes
- On boot the firmware loads ~86.5 KB of ST firmware into the VL53L5CX
  over I²C at 400 kHz — this takes ~2-3 s and is shown as a
  `firmware_loading` diagnostic event in the dashboard log.
- After initialisation the sensor enters continuous 8×8 ranging at 10 Hz.
  Each JSON line carries `{"t": <ms>, "grid": [<64 int|null>]}` where the
  grid is row-major (row 0 first) and each value is a distance in mm or
  `null` when the zone's target status is invalid.
- A FastAPI container reads `/dev/ttyACM0`, fans the JSON lines out over
  a WebSocket, and serves the dashboard at `http://localhost:18501`.
- LED indication is chip-aware — see the [Boot LED states table](../../README.md#boot-led-states)
  in the repo README.

## Hardware

| RP2040-Zero board | RP2350 | ESP32-S3-Zero | VL53L5CX ToF sensor |
|:---:|:---:|:---:|:---:|
| <img src="../../images/rp2040-zero.jpg" alt="RP2040-Zero board" width="220"> | <img src="../../images/rp2350.jpg" alt="RP2350" width="220"> | <img src="../../images/esp32-s3.jpg" alt="ESP32-S3-Zero" width="220"> | <img src="../../images/VL53L5CX.jpg" alt="VL53L5CX sensor" width="220"> |

## Wiring

### VL53L5CX ToF sensor

```
                              ┌─────────────────────┐
                              │   ┌──────────────┐  │
                              │   │  VL53L5CX IC │  │
                              │   │      ◎       │  │
                              │   └──────────────┘  │
                              │                     │
                5V ────► VIN ─┤                     │
               GND ────► GND ─┤   BREAKOUT BOARD    │
               SCL ────► SCL ─┤                     │
               SDA ────► SDA ─┤                     │
                              │                     │
                              └─────────────────────┘
```

LPN/XSHUT is pulled high on most breakout boards — no extra wiring needed.
If your board requires LPN to be driven high externally, connect it to 3V3.

### RP2040-Zero

```
                                   ┌─── USB-C ───┐
                              ┌────┴─────────────┴────┐
                              │                       │
        VL53L5CX VIN ◄───  5V ─┤                       ├─ 0  ────► VL53L5CX SDA
        VL53L5CX GND ◄─── GND ─┤                       ├─ 1  ────► VL53L5CX SCL
                         3V3 ─┤                       ├─ 2
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

The on-board WS2812 sits between the BOOT and RESET buttons on the RP2040-Zero board and is driven by GP16 — no external wiring required. I²C runs at 400 kHz (hardware I²C0).

### ESP32-S3-Zero

```
                                   ┌─── USB-C ───┐
                              ┌────┴─────────────┴────┐
                              │                       │
        VL53L5CX VIN ◄───  5V ─┤                       ├─ 13
        VL53L5CX GND ◄─── GND ─┤                       ├─ 12
                         3V3 ─┤                       ├─ 11
        VL53L5CX SDA ◄───   1 ─┤                       ├─ 10
        VL53L5CX SCL ◄───   2 ─┤                       ├─ 9
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

The on-board WS2812 is driven by GPIO21 — no external wiring required. I²C runs at 400 kHz (hardware I²C0).

### RP2350

```
                                          ┌──── USB ────┐
                              ┌───────────┴─────────────┴───────────┐
                              │                                     │
        VL53L5CX SDA ◄───   0 ─┤                                     ├─ VBUS ────► VL53L5CX VIN
        VL53L5CX SCL ◄───   1 ─┤                                     ├─ VSYS
        VL53L5CX GND ◄─── GND ─┤                                     ├─ GND
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
                          15 ─┤                                     ├─ 16
                              │                                     │
                              └─────────────────────────────────────┘
```
