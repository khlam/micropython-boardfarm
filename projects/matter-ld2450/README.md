# ESP32-S3-Zero Matter occupancy sensor

This project exposes an HLK-LD2450 mmWave radar as a Matter Occupancy Sensor.
The newest valid report is occupied when it contains at least one target beyond a radial dead zone in front of the sensor, and clear when it contains
none. Only changes are published to Matter; a timeout marks the radar unhealthy
without treating silence as an empty room.

The endpoint is read-only to controllers and declares PIR because Matter has no
radar sensing modality. The reusable radar driver remains independent of
Matter, while the project owns the translation, board wiring, and pixel. See
[`../../firmware-packages/matter/ARCHITECTURE.md`](../../firmware-packages/matter/ARCHITECTURE.md)
for the native call paths and Occupancy cluster details.

## Pixel states

The onboard WS2812 on GPIO21 shows commissioning state until pairing settles,
then radar health and occupancy. Status colors are capped at ten percent.

| Pixel | Meaning |
| --- | --- |
| Dim white | Firmware running, ESP-Matter has reported nothing yet |
| Purple | A commissioning window is open, nobody has engaged |
| Cyan | A commissioner is talking to the board |
| Solid red | The last attempt failed; purple follows within moments |
| Amber | Unpaired and advertising nothing — nobody can reach it |
| Yellow | No valid radar reports are arriving |
| Green | Occupied |
| Blue | Clear |

Pairing outranks the product state, on a paired board too — an owner adding a
second controller wants to watch that, not the radar. Once the attempt settles,
the pixel goes back to radar health and occupancy. A missing radar still does
not prevent commissioning.

Amber is the one that should never appear. An unpaired board is meant to always
be advertising, and `firmware-packages/matter` reopens a window whenever the
stack would otherwise go quiet, so amber means that recovery did not take. Red
is not latched for the same reason — a red that does not turn purple is a real
finding, whereas a red that sticks by design tells you nothing.

## USB serial and dashboard

Each valid report produces one compact JSON line containing targets outside the
dead zone. Every included target retains its raw sensor fields:

```json
{"t":1234,"targets":[{"slot":1,"x_mm":-782,"y_mm":1713,"speed_cm_s":-16,"resolution_mm":320}]}
```

The dashboard derives distance, angle, and occupancy from this report. Radar
faults use `diag` values `no_device`, `init_err`, `read_err`, or
`report_timeout`; `radar_ok` marks recovery. The Matter package also emits its
normal lifecycle and recoverable-error objects.

Start the standalone dashboard at <http://localhost:18501>:

```console
docker compose up --build viz
```

Set `SERIAL_PORT=/dev/ttyACM1` when the board is not `/dev/ttyACM0`. The plots
retain live target trails and 60 seconds of activity; occupancy returns to
`WAITING` when the serial or WebSocket connection drops.

## Build, flash, and monitor

Docker is the only host dependency. Run these commands from this directory:

```console
docker compose up --build --exit-code-from esp32-compile esp32-compile
docker compose run --rm --build esp32-flash
docker compose run --rm --build esp32-monitor
```

The build produces a merged `app.esp32-s3.bin`, its commissioning QR PNG, and a
matching setup text file under `outputs/`. Each build mints new commissioning
credentials, so keep all three artifacts together and use the codes generated
for the exact image being flashed. The named `matter-build-cache` volume keeps
incremental compiler state; `docker compose down --volumes` forces a clean
compile.

Flashing writes the complete image at `0x0`, including the partition that holds
Matter fabrics. Remove a previously flashed accessory from the controller
before commissioning the new image.

## Commissioning

In Apple Home, choose **Add Accessory** and scan `outputs/app.esp32-s3.qr.png`,
or enter the manual code in `outputs/app.esp32-s3.setup.txt`. Follow the prompts
for 2.4 GHz Wi-Fi and room assignment, then compare Home's Occupancy reading
with the onboard pixel.

A commissioned device does not reopen its initial BLE window on every boot.
Factory-reset it from the interrupted MicroPython REPL with:

```console
MONITOR_INTERRUPT=1 MONITOR_SEND='node.factory_reset()' docker compose run --rm esp32-monitor
```

`node.remove_fabric(index)` removes one fabric instead. Use the commissioning
artifacts matching the flashed image after either operation.

## Wiring

Connect board TX to radar RX and board RX to radar TX. Power the radar from 5 V
with more than 200 mA available, not from 3V3.

| ESP32-S3-Zero | UART role | HLK-LD2450 | Purpose |
| --- | --- | --- | --- |
| `5V` | — | `5V` | Radar power |
| `GND` | — | `GND` | Common power and signal ground |
| `GPIO5` | UART1 TX | `RX` | MCU commands to radar |
| `GPIO6` | UART1 RX | `TX` | Radar reports to MCU |

The radar keeps its factory 256000-baud, 8-N-1 settings. On ESP32-S3,
MicroPython implements the receive-idle UART interrupt with `Timer(0)`, which
the project reserves for the radar driver.
