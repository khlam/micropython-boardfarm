# ESP32-S3-Zero Matter occupancy sensor

This project exposes an HLK-LD2450 mmWave radar on an ESP32-S3-Zero as a Matter
Occupancy Sensor, so it pairs with Apple Home and reports whether the room is
occupied. ESP-Matter handles commissioning and protocol state; `firmware/main.py`
sets up the node, owns the radar lifecycle and the onboard pixel, and turns
target reports into the single occupied/clear bit Matter wants.

The radar reports up to three tracked targets ten times a second. Occupancy is
true while any target is present and falls back to false 15 seconds after the
last sighting. The hold matters: the LD2450 loses a motionless person for
several reports at a time, and without it a seated occupant would flicker
between occupied and clear. Only changes are published, so a still room costs no
Matter traffic.

`main.py` is the only file in the project that imports `matter`, because that is
where the service is set up. The radar driver in
[`../../firmware-packages/ld2450/`](../../firmware-packages/ld2450/) knows
nothing about Matter, and the Matter package knows nothing about radar.

## What the pixel is telling you

The onboard WS2812 on GPIO21 is a commissioning indicator until the board is
paired, then an occupancy indicator. Every colour the firmware picks for itself
is capped at ten percent of full scale.

| Pixel | Meaning |
| --- | --- |
| Dim white | Firmware running, ESP-Matter still starting |
| Solid red | Commissioning failed — stays red until the board is reset |
| Amber | No radar — the UART is open but no valid report is arriving |
| Steady purple | A commissioning window is open, nobody has engaged |
| Steady cyan | A commissioner is talking to the board |
| Steady green, unpaired | Radar healthy, uncommissioned and ready to pair |
| Steady green, paired | Occupied |
| Off | Paired and clear |

After the boot-only white baseline, higher rows win. Red is sticky until reset;
otherwise amber outranks active commissioning and the product states because a
stale "clear" is indistinguishable from a disconnected radar. Active pairing
outranks readiness and occupancy. A board with no radar attached still
commissions normally — it just sits amber until the radar answers.

## USB serial

The firmware prints nothing of its own. `esp32-monitor` shows only the `matter`
package's lifecycle JSON: `{"event":"matter","state":"ready"}` once the stack has
started and the endpoint has been restored, a commissioning line per transition,
and an `{"event":"error"}` line for a recoverable fault. Silence after `ready` is
a healthy board.

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

## Add the sensor to Apple Home

1. Power or reset the flashed board and leave it running. With the radar wired
   up, a board that has never been paired settles on green, then turns purple
   once it opens its commissioning window.
2. In Apple Home, choose **Add Accessory**.
3. Scan `outputs/app.esp32-s3.qr.png`, or enter the manual code from
   `outputs/app.esp32-s3.setup.txt`. The pixel turns cyan when Home engages.
4. Follow Apple Home's prompts to provide the 2.4 GHz Wi-Fi network and assign
   the sensor to a room.

Once paired, the accessory appears as an occupancy sensor and the pixel starts
mirroring what it reports. Occupancy is read-only to controllers: the board
publishes it, and nothing in Home can write it back.

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
