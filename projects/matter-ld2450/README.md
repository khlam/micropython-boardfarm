# ESP32-S3-Zero Matter presence switch

This project exposes an HLK-LD2450 mmWave radar on an ESP32-S3-Zero as a Matter
On/Off Plug-in Unit, so Apple Home presents it as a stateful switch suitable for
automations and scene triggers. ESP-Matter handles commissioning and protocol
state; `firmware/main.py` sets up the node, owns the radar lifecycle and the
onboard pixel, and turns target reports into the switch's Boolean OnOff value.

The radar reports up to three tracked slots ten times a second. The switch
follows the newest valid report: it is on when `len(targets) != 0` and off when
the report contains no targets. A read timeout is not a report and does not
change the switch. Only changes are published, so a still room costs no Matter
traffic. If a controller writes the switch, the next radar report restores the
slot-derived state.

`main.py` is the only file in the project that imports `matter`, because that is
where the service is set up. The radar driver in
[`../../firmware-packages/ld2450/`](../../firmware-packages/ld2450/) knows
nothing about Matter, and the Matter package knows nothing about radar.

## What the pixel is telling you

The onboard WS2812 on GPIO21 is a commissioning indicator until the board is
paired, then a switch-state indicator. Every colour the firmware picks for itself
is capped at ten percent of full scale.

| Pixel | Meaning |
| --- | --- |
| Dim white | Firmware running, ESP-Matter still starting |
| Solid red | Commissioning failed — stays red until the board is reset |
| Amber | No radar — the UART is open but no valid report is arriving |
| Steady purple | A commissioning window is open, nobody has engaged |
| Steady cyan | A commissioner is talking to the board |
| Steady green, unpaired | Radar healthy, uncommissioned and ready to pair |
| Steady green, paired | Switch on — one or more radar slots present |
| Off | Switch off — no radar slots present |

After the boot-only white baseline, higher rows win. Red is sticky until reset;
otherwise amber outranks active commissioning and the product states because a
stale "off" is indistinguishable from a disconnected radar. Active pairing
outranks readiness and switch state. A board with no radar attached still
commissions normally — it just sits amber until the radar answers.

## USB serial

`esp32-monitor` shows compact JSON diagnostics for the Python boot sequence,
pixel writes, Matter startup, radar initialization, and switch changes. A
successful pixel command ends with
`{"event":"debug","component":"pixel","state":"write_complete"}`. The `matter`
package also emits `{"event":"matter","state":"ready"}` once the stack has
started and the endpoint has been restored, a commissioning line per transition,
and an `{"event":"error"}` line for a recoverable fault.

## Live dashboard

Start the serial dashboard and open <http://localhost:18501>:

```console
docker compose up --build viz
```

It plots current radar targets, five-second motion trails, and sixty seconds of
target count, distance, and speed history. The switch box follows the
firmware's successful Matter OnOff publications and flashes when that state
changes. It returns to `WAITING` when the USB serial stream disconnects.

Set `SERIAL_PORT` when the board is not `/dev/ttyACM0`:

```console
SERIAL_PORT=/dev/ttyACM1 docker compose up --build viz
```

## Build

Docker is the only host dependency. Run commands from this directory.

Build the merged ESP32-S3 image and matching commissioning artifacts:

```console
docker compose up --build --exit-code-from esp32-compile esp32-compile
```

The build writes these files under `outputs/`:

- `app.esp32-s3.bin` is the merged firmware and factory-data image.
- `app.esp32-s3.qr.png` is the commissioning QR code for that image.
- `app.esp32-s3.setup.txt` contains the matching manual pairing code and setup
  payload.

Each build generates commissioning credentials. Keep the binary and its setup
artifacts together, and always commission with the artifacts produced alongside
the exact image that was flashed.

Compose keeps the IDF/Ninja build tree and compiler cache in the named
`matter-build-cache` volume, so a firmware-only edit recompiles only the affected
sources. To force a clean compile, run `docker compose down --volumes` first.

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

## Add the switch to Apple Home

1. Power or reset the flashed board and leave it running. With the radar wired
   up, a board that has never been paired settles on green, then turns purple
   once it opens its commissioning window.
2. In Apple Home, choose **Add Accessory**.
3. Scan `outputs/app.esp32-s3.qr.png`, or enter the manual code from
   `outputs/app.esp32-s3.setup.txt`. The pixel turns cyan when Home engages.
4. Follow Apple Home's prompts to provide the 2.4 GHz Wi-Fi network and assign
   the switch to a room.

Once paired, the accessory appears as a switch or outlet and the pixel starts
mirroring its radar-derived state. In an Apple Home automation, use the switch
turning on or off as the trigger and choose the desired scene as the action.
Home can write the OnOff attribute, but the radar is authoritative and the next
valid report restores the value derived from its slots.

## Commission again

A commissioned device does not reopen its initial BLE commissioning window on
every boot. `main.py` runs `asyncio.run(main())` at the end, so the REPL is not
reachable while the radar loop is running — interrupt it first:

```console
MONITOR_INTERRUPT=1 MONITOR_SEND='node.factory_reset()' docker compose run --rm esp32-monitor
```

`node.remove_fabric(index)` drops a single fabric instead of clearing all Matter
state. After rebuilding or factory-resetting, use the commissioning artifacts
that match the flashed image.

## Wiring

The `BOARD` table in [`firmware/main.py`](firmware/main.py) is the source of
truth for this project's pin assignment. Connect board TX to radar RX and board
RX to radar TX. Supply the radar from 5 V with more than 200 mA available; do not
use a `3V3` pin.

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

The radar is used with its factory serial settings: 256000 baud, eight data
bits, no parity, one stop bit. The firmware never changes its configuration. On
ESP32-S3, MicroPython implements the receive-idle UART interrupt with `Timer(0)`,
which this project leaves reserved for the radar driver.
