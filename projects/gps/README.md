# gps

MicroPython firmware that reads an ATGM336H GPS module over UART and collects
every NMEA sentence that arrives in a 10-second window, emitting the batch as a
single JSON line over USB-CDC. A host FastAPI service fans the lines out over a
WebSocket and serves a live dashboard with a per-window sentence-count bar chart
and a scrollable NMEA sentence log.

## Layout
```
gps/
  firmware/main.py            chip-agnostic UART collection loop, calls emit()
  viz/static/index.html       sentence-count bar chart + scrollable NMEA log
  tests/                      host pytest for the stream() behaviour
  outputs/                    build artifacts (UF2 + ESP32 bin)
  docker-compose.yaml         pi-compile / esp32-compile / esp32-flash / viz services
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

### Web dashboard
With the board plugged in (`/dev/ttyACM0`):
```bash
docker compose up --build viz
```
Open `http://localhost:18501`. The connection pill turns green when the serial
port is open. Each 10-second window adds a bar to the sentence-count chart and
populates the NMEA sentence log with every raw sentence received. The dashboard
auto-reconnects if you unplug and replug the board.

## Notes
- The firmware skips the I²C scan entirely — UART is always present. The LED
  goes from white (boot) to green (streaming) with no intermediate states.
- Each window emits one JSON batch:
  `{"t": <ms>, "window_ms": 10000, "sentences": ["$GPRMC,...", …], "count": <n>}`.
  A window with no sentences emits `{"diag": "no_data", "t": <ms>}` instead;
  UART errors emit `{"diag": "read_err", "err": "…"}` and the LED briefly turns
  red before returning to green.
- Sentences are returned as decoded ASCII strings with leading `$` intact and
  trailing `\r\n` stripped. The firmware does not parse NMEA fields — raw
  sentences are passed through unchanged for the viz to display.
- LED indication is chip-aware — see the [Boot LED states table](../../firmware-packages/boot_status_led/README.md#boot-led-states)
  in the boot_status_led README.

## Hardware

| RP2040-Zero board | RP2350 | ESP32-S3-Zero | ATGM336H GPS module |
|:---:|:---:|:---:|:---:|
| <img src="../../images/rp2040-zero.jpg" alt="RP2040-Zero board" width="220"> | <img src="../../images/rp2350.jpg" alt="RP2350" width="220"> | <img src="../../images/esp32-s3.jpg" alt="ESP32-S3-Zero" width="220"> | ATGM336H |

## Wiring

> The authoritative pin map is the `BOARD` table in [firmware/main.py](firmware/main.py);
> the per-board diagrams below mirror it.

### ATGM336H GPS module

```
                              ┌─────────────────────┐
                              │   ┌──────────────┐  │
                              │   │  ATGM336H IC │  │
                              │   │      ◎       │  │
                              │   └──────────────┘  │
                              │                     │
                5V ────► VCC ─┤                     │
               GND ────► GND ─┤   BREAKOUT BOARD    │
               MCU RX ◄── TX ─┤                     │
               MCU TX ────► RX┤  (optional — only   │
                              │   needed to send     │
                              │   NMEA commands)     │
                              └─────────────────────┘
```

**Power:** the ATGM336H module includes an onboard 3.3 V LDO, so **VCC accepts
3.3–5 V** — the 5 V USB rail is fine. The module's UART I/O is 3.3 V logic,
which is safe for all three MCU targets.

Only the GPS TX → MCU RX connection is required for receiving NMEA sentences.
The MCU TX → GPS RX line is optional and only needed if you want to send
configuration commands to the module.

### RP2040-Zero

```
                                   ┌─── USB-C ───┐
                              ┌────┴─────────────┴────┐
                              │                       │
      ATGM336H VCC ◄───  5V ─┤                       ├─ 0  ────► ATGM336H RX (opt.)
      ATGM336H GND ◄─── GND ─┤                       ├─ 1  ◄──── ATGM336H TX
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

GP1 is UART0 RX (data flows from GPS into the MCU). GP0 is UART0 TX and is
optional. The on-board WS2812 is driven by GP16 — no external wiring required.

### ESP32-S3-Zero

```
                                   ┌─── USB-C ───┐
                              ┌────┴─────────────┴────┐
                              │                       │
      ATGM336H VCC ◄───  5V ─┤                       ├─ 13
      ATGM336H GND ◄─── GND ─┤                       ├─ 12
                         3V3 ─┤                       ├─ 11
                           1 ─┤                       ├─ 10
                           2 ─┤                       ├─ 9
                           3 ─┤  [BOOT] (●) [RESET]   ├─ 8
                           4 ─┤        WS2812         ├─ 43
                           5 ─┤        on GPIO21      ├─ 44
                           6 ─┤                       ├─ 14
                           7 ─┤   ESP32-S3-Zero       ├─ 15
                              │                       │
                              └─┬────┬────┬────┬────┬─┘
                                │    │    │    │    │
                                16   17   18   21   45
                                      │    │
                    ATGM336H RX (opt.)┘    └── ATGM336H TX
```

GPIO18 is UART1 RX (data flows from GPS into the MCU). GPIO17 is UART1 TX and
is optional. The on-board WS2812 is driven by GPIO21 — no external wiring
required.

### RP2350

```
                                          ┌──── USB ────┐
                              ┌───────────┴─────────────┴───────────┐
                              │                                     │
                           0 ─┤                                     ├─ VBUS ────► ATGM336H VCC
  ATGM336H TX ────► RX(1) ──►─┤                                     ├─ VSYS
      ATGM336H GND ◄─── GND ─┤                                     ├─ GND
  ATGM336H RX ◄─── TX(0) (opt.)─┤                                     ├─ 3V3_EN
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

VBUS is the 5 V USB rail. GP1 is UART0 RX; GP0 is UART0 TX (optional).
