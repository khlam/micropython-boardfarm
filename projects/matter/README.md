# ESP32-S3-Zero Matter Color Light

This project exposes the ESP32-S3-Zero's onboard WS2812 on GPIO21 as a Matter
Extended Color Light. ESP-Matter handles commissioning and protocol state;
`firmware/main.py` sets up the node and owns the pixel, and `firmware/color/`
turns the endpoint into a plain RGB colour, so setting the LED is one call:

```python
set_color((0, 25, 0))   # green at ten percent, on the strip and in the home
```

`main.py` is the only file in the project that imports `matter`, because that is
where the service is set up.

## What the pixel is telling you

Until the board is paired the pixel is a commissioning indicator, so you can
follow a pairing attempt without a serial monitor attached:

| Pixel | Meaning |
| --- | --- |
| Dim white | Firmware running, ESP-Matter still starting |
| Steady green | Uncommissioned and ready to pair |
| Breathing purple | A commissioning window is open, nobody has engaged |
| Breathing cyan | A commissioner is talking to the board |
| Solid red | Commissioning failed — stays red until the board is reset |
| Off | Commissioned; the pixel now belongs to the controller |

Every colour the firmware picks for itself is capped at ten percent of full
scale, because a status light has no business being the brightest thing in the
room. Only a controller-commanded level is allowed to reach maximum, and a
controller write renders at exactly the level it asks for.

Commissioning succeeding turns the pixel off *and* publishes `OnOff` as false,
so the accessory shows as off in the home rather than claiming to be lit while
the board is dark.

## Build and flash

Docker is the only host dependency. From this directory, build the merged
firmware and its matching commissioning artifacts:

```console
docker compose up --build --exit-code-from esp32-compile esp32-compile
```

The build produces three files under `outputs/`:

- `app.esp32-s3.bin` is the merged firmware and factory-data image.
- `app.esp32-s3.qr.png` is the commissioning QR code for that image.
- `app.esp32-s3.setup.txt` contains the matching manual pairing code and setup
  payload.

Each build generates commissioning credentials. Always commission with the QR
code or manual code produced alongside the exact binary that was flashed.

Put the ESP32-S3-Zero in its bootloader mode and flash it with:

```console
docker compose run --rm --build esp32-flash
```

Set `SERIAL_PORT` when the board is not `/dev/ttyACM0`:

```console
SERIAL_PORT=/dev/ttyACM1 docker compose run --rm --build esp32-flash
```

## Watch the board

```console
docker compose run --rm --build esp32-monitor
```

Reads `$SERIAL_PORT` for `MONITOR_SECONDS` (default 90) and prints each line with
its offset from the start of the capture. A healthy boot prints
`{"event":"matter","state":"ready"}` once the stack has started and the endpoint
has been restored, then stays silent; a traceback or an `{"event":"error"}` line
is the failure.

`MONITOR_PROBE=1` sends a newline on connect — a `>>>` prompt in the reply means
no program is running. `MONITOR_SEND='…'` types one line at the REPL, and
`MONITOR_INTERRUPT=1` sends Ctrl-C first so a running program stops and the REPL
can accept it.

## Add the light to Apple Home

1. Power or reset the flashed board and leave it running. A board that has never
   been paired settles on green, then breathes purple once it opens its window.
2. In Apple Home, choose **Add Accessory**.
3. Scan `outputs/app.esp32-s3.qr.png`, or enter the manual code from
   `outputs/app.esp32-s3.setup.txt`. The breath turns cyan when Home engages.
4. Follow Apple Home's prompts to provide the 2.4 GHz Wi-Fi network and assign
   the light to a room. The pixel goes dark on success and the light appears in
   Home switched off — turn it on there to take the pixel over.

Once the light is on, whichever side wrote most recently is what the pixel
shows. Both directions are plain functions in `firmware/main.py` that funnel
through the same `render()` helper, which is the only place that touches
`pixel[0] = color; pixel.write()`:

- A color, brightness or power change from a controller wakes
  `on_remote_write()`, which reads the colour back off the endpoint and drives
  the strip.
- `set_color(rgb)` drives the strip and then publishes the same color back,
  turning the light on. A local write shows exactly the bytes written, while the
  endpoint holds the nearest color its hue, saturation and level can represent.

`main.py` runs top to bottom at boot and then drops to the REPL, so `set_color`,
`node`, `endpoint` and `pixel` are all still in scope over serial:

```console
MONITOR_INTERRUPT=1 MONITOR_SEND='set_color((0, 25, 0))' docker compose run --rm esp32-monitor
```

## Commission again

A commissioned device does not reopen its initial BLE commissioning window on
every boot. From the MicroPython REPL, remove an individual fabric with
`node.remove_fabric(index)` or clear all Matter state and reboot with:

```python
node.factory_reset()
```

After rebuilding or factory-resetting, use the commissioning artifacts that
match the flashed image.
