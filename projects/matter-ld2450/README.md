# Matter LD2450 firmware scaffold

This directory is the ESP32-S3 firmware project scaffold for combining an
HLK-LD2450 radar with Matter. It includes the native Matter board definition,
Docker build/flash/monitor services, and a frozen MicroPython entry point.

The entry point records the board and radar UART wiring but is otherwise inert:
it does not start the Matter stack, open the UART, or choose a Matter endpoint
schema. Those behaviors belong in `firmware/main.py` once the product contract
is defined.

## Build

Docker is the only host dependency. Run commands from this directory.

Build the merged ESP32-S3 image and matching commissioning artifacts:

```console
docker compose up --build --exit-code-from esp32-compile esp32-compile
```

The build writes these files under `outputs/`:

- `app.esp32-s3.bin`
- `app.esp32-s3.qr.png`
- `app.esp32-s3.setup.txt`

Each build generates commissioning credentials. Keep the binary and its setup
artifacts together.

## Flash and monitor

Put the ESP32-S3-Zero in bootloader mode, then compile and flash it:

```console
docker compose run --rm --build esp32-flash
```

Read its USB serial output without rebuilding or flashing:

```console
docker compose run --rm --build esp32-monitor
```

Set `SERIAL_PORT` when the board is not `/dev/ttyACM0`.

## Wiring

The `BOARD` table in [`firmware/main.py`](firmware/main.py) is the source of
truth for this project's pin assignment. Connect board TX to radar RX and board
RX to radar TX:

| ESP32-S3-Zero | UART role | HLK-LD2450 | Purpose |
| --- | --- | --- | --- |
| `5V` | — | `5V` | Radar power |
| `GND` | — | `GND` | Common power and signal ground |
| `GPIO5` | UART1 TX | `RX` | MCU commands to radar |
| `GPIO6` | UART1 RX | `TX` | Radar reports to MCU |

```text
HLK-LD2450                           ESP32-S3-Zero
                                  ┌────── USB-C ──────┐
  5V ◄────────────────────────────┤ 5V       GPIO43/TX├
 GND ─────────────────────────────┤ GND      GPIO44/RX├
                                  ┤ 3V3        GPIO13 ├
                                  ┤ GPIO1      GPIO12 ├
                                  ┤ GPIO2      GPIO11 ├
                                  ┤ GPIO3      GPIO10 ├
                                  ┤ GPIO4       GPIO9 ├
  RX ◄── UART1 TX ────────────────┤ GPIO5       GPIO8 ├
  TX ─── UART1 RX ───────────────►┤ GPIO6       GPIO7 ├
                                  └── WS2812: GPIO21 ─┘
```
