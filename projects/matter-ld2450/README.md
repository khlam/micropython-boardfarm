# ESP32-S3-Zero Matter occupancy toggle

**This project is currently a controller bring-up test, not a radar sensor.**
The radar is not opened at all. `firmware/main.py` publishes two Matter
Occupancy Sensor endpoints and flips them on a one-minute timer so their
behaviour in a controller can be observed with nothing else in the way.

It answers two questions about Apple Home:

1. Does Home track this device's sensing state at all? Nothing but the timer can
   move an attribute here, so a tile that never changes is a controller or
   schema problem rather than a sensor problem.
2. Which of Home's **Motion** and **Occupancy** room categories does each
   endpoint land in? Matter has no separate motion-sensor device type, so the
   declared sensing modality is the only lever a controller could sort them by.

The two endpoints are identical apart from that modality — one declares PIR, the
other ultrasonic — and they are driven in opposite phase, so they are never
equal and each one's tile is identifiable on sight:

| Elapsed | `motion` endpoint (PIR) | `occupancy` endpoint (ultrasonic) |
| --- | --- | --- |
| 0:00 | off | on |
| 1:00 | on | off |
| 2:00 | off | on |

`main.py` is the only file in the project that imports `matter`, because that is
where the service is set up.

## What the pixel is telling you

The onboard WS2812 on GPIO21 is a commissioning indicator until the board is
paired, then a phase indicator. Every colour the firmware picks for itself is
capped at ten percent of full scale.

| Pixel | Meaning |
| --- | --- |
| Dim white | Firmware running, ESP-Matter still starting |
| Solid red | Commissioning failed — stays red until the board is reset |
| Steady purple | A commissioning window is open, nobody has engaged |
| Steady cyan | A commissioner is talking to the board |
| Steady green, unpaired | Uncommissioned and ready to pair |
| Steady green, paired | `motion` on, `occupancy` off |
| Steady blue | `motion` off, `occupancy` on |

After the boot-only white baseline, higher rows win. Red is sticky until reset;
active pairing outranks the toggle phase, which has a full minute to be read
while the pairing colours do not. Green alternating with blue once a minute is
the firmware working — if the pixel is flipping and Home is not, the problem is
past the device.

## USB serial

`esp32-monitor` shows compact JSON diagnostics for the Python boot sequence,
pixel writes, Matter startup, and every published phase. Each phase emits one
line per endpoint —
`{"event":"debug","component":"toggle","endpoint":"motion","endpoint_id":1,"state":"off"}`
— and a `"state":"publish_failed"` line carrying the error instead when
ESP-Matter refuses the write. A successful pixel command ends with
`{"event":"debug","component":"pixel","state":"write_complete"}`. The `matter`
package also emits `{"event":"matter","state":"ready"}` once the stack has
started and the endpoints have been restored, a commissioning line per
transition, and an `{"event":"error"}` line for a recoverable fault.

## Live dashboard

Start the serial dashboard and open <http://localhost:18501>:

```console
docker compose up --build viz
```

The radar plots stay empty while this firmware is loaded — no targets are being
streamed. Only the occupancy box moves, following the `occupancy` endpoint's
published phase and flashing each time it flips. It returns to `WAITING` when
the USB serial stream disconnects.

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

## Add the sensor to Apple Home

1. Power or reset the flashed board and leave it running. A board that has never
   been paired settles on green, then turns purple once it opens its
   commissioning window.
2. In Apple Home, choose **Add Accessory**.
3. Scan `outputs/app.esp32-s3.qr.png`, or enter the manual code from
   `outputs/app.esp32-s3.setup.txt`. The pixel turns cyan when Home engages.
4. Follow Apple Home's prompts to provide the 2.4 GHz Wi-Fi network and assign
   both endpoints to a room.

Every compile mints a fresh discriminator, passcode, and salt, so a QR code
saved from an earlier build will not pair this one. Use the artifacts sitting in
`outputs/` next to the image you just flashed.

Flashing writes a full-flash image at `0x0`, which overwrites the `nvs`
partition holding Matter fabrics. A reflashed board is therefore no longer
commissioned: remove the old accessory in Home before adding it again.

Once paired, watch the room's **Motion** and **Occupancy** readings against the
pixel. Occupancy is read-only to controllers: the board publishes it, and
nothing in Home can write it back.

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
