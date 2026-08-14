# HLK-LD2450 live radar

Multi-board demo for the Hi-Link HLK-LD2450, supporting RP2040-Zero, RP2350,
and ESP32-S3-Zero. The reusable driver decodes the radar's 10 Hz binary UART
stream, firmware emits compact JSON over USB-CDC, and the shared FastAPI
service publishes it to a live Plotly dashboard. The driver accepts reusable
UART identifiers and pins; each project owns its own board's pin map.

## Usage

Run commands from this directory.

### RP2040-Zero / RP2350

Compile the universal image:

```bash
docker compose up --build pi-compile
```

Use `outputs/app.rp2040.rp2350.uf2` on either board. Put the board in
[bootloader mode](../microcontrollers.md#bootloader-mode), then copy the UF2 to
the `RPI-RP2` drive.

### ESP32-S3-Zero

Put the board in [bootloader mode](../microcontrollers.md#bootloader-mode) —
the service fails fast if `/dev/ttyACM0` isn't present. Compile and flash:

```bash
docker compose run --rm --build esp32-flash
```

Runs `esp32-compile` to produce `outputs/app.esp32-s3.bin`, then immediately
flashes it via `esptool.py` running inside the container.

### Web dashboard

With the flashed board connected, launch the dashboard and open
<http://localhost:18501>:

```bash
docker compose up --build viz
```

The service defaults to `/dev/ttyACM0` and reconnects after unplug/replug. To
select another port:

```bash
SERIAL_PORT=/dev/ttyACM1 docker compose up --build viz
```

On macOS, start the repository's
[serial bridge](../../tools/serial-bridge/serial-bridge.md) and use
`SERIAL_PORT=socket://host.docker.internal:5555`.

The dashboard shows current X/Y positions, five-second trails, the documented
6 m ±60° coverage guide, per-slot position/distance/angle/speed/resolution,
60-second target-count/distance/speed charts, connection state, freshness,
frame rate, frame count, and firmware diagnostics. Radar slots are not durable
person identities.

## JSON stream

The freshest available report is emitted, including reports with no active targets.
`distance_mm` and `angle_deg` are derived from `x_mm`/`y_mm` on the MCU so the
dashboard and any other consumer plot ready-to-use polar values instead of
recomputing them per frame:

```json
{"t":1234,"targets":[{"slot":1,"x_mm":-782,"y_mm":1713,"speed_cm_s":-16,"resolution_mm":320,"distance_mm":1884,"angle_deg":-24}]}
```

`targets` contains zero to three objects. Buffered older reports are discarded
if the consumer falls behind so the visualization stays current. Diagnostics
use a separate shape:

```json
{"diag":"frame_timeout","t":1734}
```

Initialization distinguishes `no_device` from `init_err`. Streaming emits
`frame_timeout` once per timeout period, resumes on the next valid report, and
uses `read_err` for UART failures.

## Wiring

The authoritative mapping is the `BOARD` table in `firmware/main.py`. UART TX
and RX cross between the devices. Supply the radar from 5 V with more than
200 mA available; do not use a `3V3` pin. The radar's UART uses 3.3 V logic,
so none of the three boards need a level shifter. If using a separate
regulated supply, join its ground to the MCU's `GND`.

### RP2040-Zero

| RP2040-Zero | UART role | HLK-LD2450 | Purpose |
| --- | --- | --- | --- |
| `5V` | — | `5V` | Radar power |
| `GND` | — | `GND` | Common power and signal ground |
| `GP4` | UART1 TX | `RX` | MCU to radar |
| `GP5` | UART1 RX | `TX` | Radar reports to MCU |

### RP2350

| RP2350 | UART role | HLK-LD2450 | Purpose |
| --- | --- | --- | --- |
| `VBUS` | — | `5V` | Radar power |
| `GND` | — | `GND` | Common power and signal ground |
| `GP0` | UART0 TX | `RX` | MCU to radar |
| `GP1` | UART0 RX | `TX` | Radar reports to MCU |

### ESP32-S3-Zero

| ESP32-S3-Zero | UART role | HLK-LD2450 | Purpose |
| --- | --- | --- | --- |
| `5V` | — | `5V` | Radar power |
| `GND` | — | `GND` | Common power and signal ground |
| `GPIO17` | UART1 TX | `RX` | MCU to radar |
| `GPIO18` | UART1 RX | `TX` | Radar reports to MCU |

The demo expects the factory 256000-baud, 8-N-1 setting and never changes radar
configuration. See the
[Hi-Link LD2450 serial protocol V1.03](https://h.hlktech.com/download/HLK-LD2450-24G/1/LD2450%20%E4%B8%B2%E5%8F%A3%E9%80%9A%E4%BF%A1%E5%8D%8F%E8%AE%AE%20V1.03.pdf).

The reusable parser is documented in
[`../../firmware-packages/ld2450/`](../../firmware-packages/ld2450/).
