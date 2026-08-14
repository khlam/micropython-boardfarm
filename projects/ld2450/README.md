# HLK-LD2450 live radar

RP2040-Zero MicroPython demo for the Hi-Link HLK-LD2450. The reusable driver
decodes the radar's 10 Hz binary UART stream, firmware emits one compact JSON
object per report over USB-CDC, and the shared FastAPI host service publishes it
to a live Plotly dashboard over WebSocket.

The first demo supports RP2040-Zero. The `ld2450` package itself accepts flat
UART identifiers and pins and can be reused by other MicroPython projects.

## Data path

```text
LD2450 @ 256000 baud ──UART1──► RP2040-Zero ──USB-CDC JSON──► FastAPI/WebSocket ──► browser
```

The radar-side UART and host-side USB serial connection are independent. The
host service keeps its standard 115200 USB serial setting; it never connects
directly to the radar.

## Usage

Run commands from this directory.

### Compile and flash RP2040-Zero

```bash
docker compose up --build pi-compile
```

This produces `outputs/app.rp2040.uf2` and `outputs/app.rp2350.uf2`. This project
runs only on RP2040; the RP2350 image emits `unsupported_mcu`. Put the
RP2040-Zero in [bootloader mode](../microcontrollers.md#bootloader-mode), then
drag `outputs/app.rp2040.uf2` onto the `RPI-RP2` drive.

The project selects `RP_UF2_MODE=separate` in Compose. The shared compiler's
default remains the existing universal UF2 for projects that do not set it.

### Launch the dashboard

With the flashed board connected:

```bash
docker compose up --build viz
```

Open <http://localhost:18501>. The service defaults to `/dev/ttyACM0` and
automatically reconnects after an unplug/replug. Override the port when needed:

```bash
SERIAL_PORT=/dev/ttyACM1 docker compose up --build viz
```

On macOS, start the repository's
[serial bridge](../../tools/serial-bridge/serial-bridge.md) and use its
`socket://host.docker.internal:5555` URL.

## Dashboard

The browser shows:

- Current X/Y positions and five-second trails for report slots 1–3.
- A fixed-aspect 6 m, ±60° coverage guide.
- Per-slot X, Y, derived distance and angle, signed speed, and range resolution.
- Sixty-second charts for active target count, distance by slot, and signed
  speed by slot.
- USB connection, data freshness, frame rate, frame count, and firmware
  diagnostics.

Slots are report positions chosen by the radar, not durable person identities.
Missing slots and radar timeouts create gaps in analytics. A firmware timestamp
reset clears retained history rather than joining data across boots.

## JSON schema

Every valid radar report is emitted, including reports with no active targets:

```json
{"t":1234,"targets":[{"slot":1,"x_mm":-782,"y_mm":1713,"speed_cm_s":-16,"resolution_mm":320}]}
```

`targets` contains zero to three objects. Diagnostics use a separate shape:

```json
{"diag":"frame_timeout","t":1734}
```

Initialization distinguishes `no_device` from `init_err`; streaming reports
`frame_timeout` only on entry into a timeout period and resumes automatically
when valid frames return. UART failures report `read_err`.

## Wiring

The authoritative mapping is the `BOARD` selection in `firmware/main.py`.
UART lines cross because each TX connects to the other device's RX.

| RP2040-Zero | UART role | HLK-LD2450 | Purpose |
| --- | --- | --- | --- |
| `5V` | — | `5V` | Radar power |
| `GND` | — | `GND` | Common power and signal ground |
| `GP4` | UART1 TX | `RX` | MCU to radar; retained for future commands |
| `GP5` | UART1 RX | `TX` | Radar target reports to MCU |

```text
                 Waveshare RP2040-Zero                 HLK-LD2450
              (USB-C connector at top)             (labelled interface)

                    ┌───────────┐                    ┌───────────┐
 USB 5 V rail   5V ─┤           ├───────────────────►│ 5V        │
 Common ground GND ─┤           ├───────────────────►│ GND       │
 UART1 TX       GP4 ┤           ├───────────────────►│ RX        │
 UART1 RX       GP5 ┤           ├◄───────────────────│ TX        │
                    └───────────┘                    └───────────┘
```

The LD2450 requires 5 V with more than 200 mA available. Its UART uses 3.3 V
logic, so GP4 and GP5 connect directly without a level shifter. Do not power the
radar from the board's `3V3` pin. If a separate regulated 5 V supply is used,
join its ground to RP2040-Zero `GND`.

Use either the radar socket or its pin interface and follow the printed signal
labels because carrier layouts can differ. The demo expects the factory UART
setting: 256000 baud, eight data bits, no parity, one stop bit. A radar changed
to another baud must be restored externally.

Sources: [Hi-Link LD2450 serial protocol V1.03](https://h.hlktech.com/download/HLK-LD2450-24G/1/LD2450%20%E4%B8%B2%E5%8F%A3%E9%80%9A%E4%BF%A1%E5%8D%8F%E8%AE%AE%20V1.03.pdf),
[Hi-Link product specifications](https://www.hlktech.com/Goods-226.html), and
[Waveshare RP2040-Zero documentation](https://www.waveshare.com/wiki/RP2040-Zero).

## Layout

```text
ld2450/
  firmware/main.py          RP2040 board map, radar lifecycle, JSON stream
  viz/static/index.html     live target map and 60-second analytics
  docker-compose.yaml       RP compile and host visualization services
  pyproject.toml            project metadata
  tests/                    added after feature confirmation
```

The reusable parser is documented in
[`../../firmware-packages/ld2450/`](../../firmware-packages/ld2450/).

## Test status

Automated driver and project tests will replace the placeholders after the
feature behavior is confirmed, as required by the repository testing policy.
