# gyro-stream

MicroPython firmware that reads an MPU6050 IMU and streams accelerometer, gyro, and temperature
samples as JSON lines over USB-CDC at ~100 Hz. A host FastAPI service
fans the lines out over a WebSocket and serves a live Plotly dashboard
with a 3D orientation view.

## Layout
```
gyro-stream/
  firmware/main.py            chip-agnostic streaming loop, calls emit()
  viz/static/index.html       Plotly multi-trace + 3D orientation view
  tests/                      host pytest for the emit() schema
  outputs/                    compiled firmware artifacts (UF2 + ESP32 bin)
  docker-compose.yaml         pi-compile / esp32-compile / esp32-flash / viz services
```

## Usage

### RP2040 / RP2350
1. Compile the firmware:
   ```bash
   docker compose up --build pi-compile
   ```
   A single compile produces one universal file at [outputs/app.rp2040.rp2350.uf2](outputs/app.rp2040.rp2350.uf2) that flashes correctly on either device.
2. Put the board in [bootloader mode](../../README.md#bootloader-mode).
3. Drag-and-drop [outputs/app.rp2040.rp2350.uf2](outputs/app.rp2040.rp2350.uf2) onto the mounted USB drive. The board ejects and reboots running the new firmware.

### ESP32-S3
1. Put the board in [bootloader mode](../../README.md#bootloader-mode) — the service fails fast if `/dev/ttyACM0` isn't present.
2. Compile and flash:
   ```bash
   docker compose up --build --exit-code-from esp32-flash esp32-flash
   ```
   Runs `esp32-compile`, then flashes [outputs/app.esp32-s3.bin](outputs/app.esp32-s3.bin) via `esptool.py` inside the container.

### Web dashboard
With the board plugged in (`/dev/ttyACM0`):
```bash
docker compose up --build viz
```
Open `http://localhost:18501`. The connection pill turns green when the
serial port is open, and the 3D orientation panel + accel/gyro/temp line
charts + roll/pitch readouts update in real time. The dashboard
auto-reconnects if you unplug and replug the board.

## Notes
- The firmware initialises I²C, tries the MPU6050 at `0x68` (AD0=GND/floating)
  then `0x69` (AD0=3V3), auto-detects the chip variant via WHO_AM_I, and
  enters a streaming loop that prints one JSON line per sample.
- Sample shape: `{"t": <ms>, "ax": <g>, "ay": <g>, "az": <g>, "gx": <°/s>, "gy": <°/s>, "gz": <°/s>, "T": <°C>}`.
  Diagnostic events use the `diag` namespace (`scan`, `no_device`,
  `init_err`, `imu_ok`, `read_err`, `sat`).
- LED indication is chip-aware — see the [Boot LED states table](../../README.md#boot-led-states)
  in the repo README.

## Hardware

| RP2040-Zero board | RP2350 | ESP32-S3-Zero | MPU6050 IMU |
|:---:|:---:|:---:|:---:|
| <img src="../../images/rp2040-zero.jpg" alt="RP2040-Zero board" width="220"> | <img src="../../images/rp2350.jpg" alt="RP2350" width="220"> | <img src="../../images/esp32-s3.jpg" alt="ESP32-S3-Zero" width="220"> | <img src="../../images/MPU6050.jpg" alt="MPU6050 IMU" width="220"> |

## Wiring

### MPU6050 IMU

```
                              ┌─────────────────────┐
                              │   ┌──────────────┐  │
                              │   │  MPU6050 IC  │  │
                              │   │      ◎       │  │
                              │   └──────────────┘  │
                              │                     │
                5V ────► VCC ─┤                     │
               GND ────► GND ─┤   BREAKOUT BOARD    │
               SCL ────► SCL ─┤                     │
               SDA ────► SDA ─┤                     │
                              │                     │
                              └─────────────────────┘
```

AD0 can be left floating (→ address `0x68`) or tied to 3V3 (→ address `0x69`); the firmware tries both.

### RP2040-Zero

```
                                   ┌─── USB-C ───┐
                              ┌────┴─────────────┴────┐
                              │                       │
        MPU6050 VCC ◄───  5V ─┤                       ├─ 0  ────► MPU6050 SDA
        MPU6050 GND ◄─── GND ─┤                       ├─ 1  ────► MPU6050 SCL
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

The on-board WS2812 sits between the BOOT and RESET buttons on the RP2040-Zero board and is driven by GP16 — no external wiring required.

### ESP32-S3-Zero

```
                                   ┌─── USB-C ───┐
                              ┌────┴─────────────┴────┐
                              │                       │
        MPU6050 VCC ◄───  5V ─┤                       ├─ 13
        MPU6050 GND ◄─── GND ─┤                       ├─ 12
                         3V3 ─┤                       ├─ 11
        MPU6050 SDA ◄───   1 ─┤                       ├─ 10
        MPU6050 SCL ◄───   2 ─┤                       ├─ 9
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
        MPU6050 SDA ◄───   0 ─┤                                     ├─ VBUS ────► MPU6050 VCC
        MPU6050 SCL ◄───   1 ─┤                                     ├─ VSYS
        MPU6050 GND ◄─── GND ─┤                                     ├─ GND
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
