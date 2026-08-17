# Matter LD2450 firmware scaffold

This directory is the ESP32-S3 firmware project scaffold for combining an
HLK-LD2450 radar with Matter. It includes the native Matter board definition,
Docker build/flash/monitor services, and a frozen MicroPython entry point.

The entry point is intentionally inert: it does not start the Matter stack,
open the radar UART, or choose a Matter endpoint schema. Those behaviors belong
in `firmware/main.py` once the product contract is defined.

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

## Reserved radar wiring

The intended UART wiring follows the existing LD2450 project:

| ESP32-S3-Zero | HLK-LD2450 | Purpose |
| --- | --- | --- |
| `5V` | `5V` | Radar power |
| `GND` | `GND` | Common power and signal ground |
| `GPIO17` | `RX` | UART1 transmit to radar |
| `GPIO18` | `TX` | UART1 receive from radar |

The radar requires a 5 V supply capable of more than 200 mA. Its UART signal is
3.3 V.
