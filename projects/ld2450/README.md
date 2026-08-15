# HLK-LD2450 live radar

This project displays the targets detected by an HLK-LD2450 radar. It supports
the RP2040-Zero, RP2350, and ESP32-S3-Zero boards.

The radar sends ten reports per second over a UART serial connection. Each
report has three target slots. The firmware reads the report, sends the active
targets as JSON over the board's USB serial connection, and the web dashboard
plots their positions. The `BOARD` table in `firmware/main.py` selects the UART
and GPIO pins for each board.

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
6 m ±60° coverage guide, and the position, distance, angle, speed, and distance
resolution for each target. It also shows 60-second charts, connection status,
report age, report rate, report count, and firmware status messages. A slot
number identifies a place in one radar report; it does not identify a person.

## USB serial data

Each line sent over USB is one JSON object. The firmware sends the newest radar
report, including reports with no targets. It calculates `distance_mm` and
`angle_deg` from `x_mm` and `y_mm` so every display uses the same values:

```json
{"t":1234,"targets":[{"slot":1,"x_mm":-782,"y_mm":1713,"speed_cm_s":-16,"resolution_mm":320,"distance_mm":1884,"angle_deg":-24}]}
```

`targets` contains zero to three objects. If several reports are waiting, the
firmware skips older ones so the display stays current. Status messages use a
different JSON form:

```json
{"diag":"report_timeout","t":1734}
```

`no_device` means no valid radar report arrived during startup. `init_err`
means the UART could not be opened. While running, `report_timeout` means a
report did not arrive within 500 ms, and `read_err` means a UART read failed.
Normal output resumes when the next valid report arrives.

## Wiring

The `BOARD` table in `firmware/main.py` is the source of truth for the wiring.
UART is the two-wire serial connection between the board and radar. Connect
board TX to radar RX and board RX to radar TX. Supply the radar from 5 V with
more than 200 mA available; do not use a `3V3` pin. The UART signal uses 3.3 V,
so these boards do not need a level shifter. If the radar has a separate power
supply, connect its ground to the board's `GND`.

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

The demo expects the factory serial settings: 256000 baud, eight data bits, no
parity, and one stop bit. It never changes the radar configuration. See the
[Hi-Link LD2450 serial protocol V1.03](https://h.hlktech.com/download/HLK-LD2450-24G/1/LD2450%20%E4%B8%B2%E5%8F%A3%E9%80%9A%E4%BF%A1%E5%8D%8F%E8%AE%AE%20V1.03.pdf).

The reusable radar driver is documented in
[`../../firmware-packages/ld2450/`](../../firmware-packages/ld2450/).
