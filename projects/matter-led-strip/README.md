# ESP32-S3-Zero Matter LED Strip

This project exposes an external WS2812B strip of up to 25 LEDs wired to the
ESP32-S3-Zero as a Matter Extended Color Light, seven virtual On/Off pattern
lights, and a virtual dimmer that selects the active LED count. ESP-Matter handles
commissioning and protocol state; `firmware/main.py` sets up the node and
owns the strip, and `firmware/color/` turns the endpoint into a plain RGB
colour, so setting the strip is one call:

```python
set_color((0, 25, 0))   # green at ten percent, on the strip and in the home
```

`main.py` is the only file in the project that imports `matter`, because that is
where the service is set up.

## Wiring

`DIN` goes to `GPIO4`. Common ground is mandatory: board `GND`, strip `GND`,
and the 5V supply must share a ground or the data line has no reference.

```
                                   ┌─── USB-C ───┐
                              ┌────┴─────────────┴────┐
                              │                       │
         WS2812B 5V ◄───  5V ─┤                       ├─ 13
        WS2812B GND ◄─── GND ─┤                       ├─ 12
                         3V3 ─┤                       ├─ 11
                           1 ─┤                       ├─ 10
                           2 ─┤                       ├─ 9
                           3 ─┤  [BOOT] (●) [RESET]   ├─ 8
        WS2812B DIN ◄───   4 ─┤        WS2812         ├─ 43
                           5 ─┤        on GPIO21      ├─ 44
                           6 ─┤                       ├─ 14
                           7 ─┤   ESP32-S3-Zero       ├─ 15
                              │                       │
                              └─┬────┬────┬────┬────┬─┘
                                │    │    │    │    │
                                16   17   18   21   45
```

## What the status LEDs are telling you

Both the onboard WS2812 (GPIO21) and the external strip ("the ring") carry a
commissioning indicator, so you can follow a pairing attempt without a serial
monitor attached. Once the board is commissioned, the ring reverts to being
reserved for the real, controller-meaningful light state — the pairing/status
colours below only ever appear on it before that point:

| State | Onboard LED | Ring |
| --- | --- | --- |
| Firmware running, ESP-Matter still starting | Dim white (steady) | Off |
| Uncommissioned, ready to pair | Dim cyan (steady) | Dim cyan (steady) |
| A commissioning window is open, nobody has engaged | Dim cyan (steady) | Dim cyan (steady) |
| A commissioner is talking to the board | Dim cyan (steady) | Dim cyan (steady) |
| Commissioning failed — onboard stays red until the board is reset | Solid red (steady) | Red, blinking 0.5s on every 3s |
| Commissioned | Dim green (steady) | Last colour a controller set (see below) |

Ready, window-open, and commissioner-session indications are intentionally
identical.

Every colour the firmware picks for itself is capped at ten percent of full
scale, because a status light has no business being the brightest thing in the
room. Only a controller-commanded level is allowed to reach maximum on the
strip, and a controller write renders at exactly the level it asks for.

Commissioning succeeding turns the strip off *and* publishes `OnOff` as false,
so the accessory shows as off in the home rather than claiming to be lit while
the board is dark; the onboard LED switches to its dim-green "commissioned"
colour at the same moment. On later boots, a commissioned board restores the
last controller-owned power, brightness, and colour on the strip directly,
and the onboard LED goes straight to dim green without ever showing the boot
indicator. Opening a new commissioning window shows its status colour and
pattern on both LEDs; closing it restores the controller-owned light state on
the strip and dim green on the onboard LED, or dim cyan on both if the board
still isn't commissioned.

## Boot-cache behaviour

Once the strip has shown a real controller-owned colour while commissioned, a
power cycle shows that exact colour on the configured LED prefix immediately — the onboard
status LED never lights its dim-white boot or dim-cyan "ready" colour, going
straight to its dim-green "commissioned" colour once `node.start()` confirms
the fabric — and holds it until ESP-Matter's own restore confirms it (the
normal case, silent) or a genuine new remote write arrives. This is separate
from ESP-Matter's own persistence: `firmware/boot_cache.py` keeps a small
local copy of the last colour in a dedicated flash partition (`boot_cache` in
`native/board/ESP32_S3_MATTER/partitions.csv`) precisely because ESP-Matter's
own store isn't readable until `node.start()` returns,
which is the one thing this behaviour needs to happen before. The same cache
holds the active external LED count, defaulting to 20 when reading cache data
that does not yet contain it. A board that has
never been commissioned, or has been commissioned but never yet given a real
colour command, still shows the ordinary boot indicator above, with the ring
held off.

## Build and flash

Docker is the only host dependency. From this directory, build the merged
firmware and its matching commissioning artifacts:

```console
docker compose up --build --exit-code-from esp32-compile esp32-compile
```

Compose keeps the IDF/Ninja build tree and compiler cache in the named
`matter-build-cache` volume. Rebuilding the toolchain image does not discard that
volume, so a firmware-only edit recompiles only the affected sources. To force a
fully clean compile, remove the cache with `docker compose down --volumes` before
running the build again.

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
   been paired settles on dim cyan across both LEDs, and stays there once it
   opens its window.
2. In Apple Home, choose **Add Accessory**.
3. Scan `outputs/app.esp32-s3.qr.png`, or enter the manual code from
   `outputs/app.esp32-s3.setup.txt`. Both LEDs remain dim cyan while Home
   engages.
4. Follow Apple Home's prompts to provide the 2.4 GHz Wi-Fi network and assign
   the light to a room. The onboard LED settles on dim green on success and
   the light appears in Home switched off — turn it on there to take the
   strip over.
5. Find the additional dimmable-light service after the seven pattern lights
   and rename it **LED Count**. Apple Home chooses generated service names, so
   the firmware cannot assign that tile name itself.

Once the light is on, whichever side wrote most recently is what the strip
shows. Both directions are plain functions in `firmware/main.py` that funnel
through the project renderer; commissioning owns the strip while its status
overlay is active, then releases it back to the selected application pattern:

- A color, brightness or power change from a controller wakes
  `on_remote_write()`, which reads the colour back off the endpoint and drives
  the strip.
- `set_color(rgb)` drives the strip and then publishes the same color back,
  turning the light on. A local write shows exactly the bytes written, while the
  endpoint holds the nearest color its hue, saturation and level can represent.

## LED count slider

The **LED Count** virtual dimmer selects an active prefix of 1-25 external LEDs.
Its full brightness range is divided evenly into 25 positions: the bottom
selects one LED, the midpoint selects 13, and the top selects 25. The firmware
snaps the Matter level to the nearest position, so the selection persists across
reboots even though Apple Home displays a percentage rather than an LED count.
The initial selection is 20 LEDs.

The selector cannot be disabled. Turning its light tile off preserves the
current count and the firmware publishes it on again. Reducing the count writes
black to every LED above the selected prefix before flushing the strip, including
while a pattern is active. The onboard status WS2812 on GPIO21 is a separate
device and is never included in this count.

## Pattern switches

Matter controllers expose seven additional On/Off light endpoints in this
order: **Random**, **Breathe**, **Wave**, **Alternate**, **Rainbow**, **Chase**,
and **Twinkle**. Turn one on to select it; the firmware turns every other
pattern endpoint off. Turn the active endpoint off to select **None** and show
the steady selected color. Controllers choose the initial tile names, so rename
the seven services in that order when their generated names are not descriptive.

| Mode | Behavior |
| --- | --- |
| None | Steady selected color |
| Random | New saturated color on every pixel every 500 ms |
| Breathe | Three-second selected-color pulse |
| Wave | Selected-color brightness wave traveling across the strip every 2.5 seconds |
| Alternate | Selected-color and black pixels swap every 600 ms |
| Rainbow | Full-strip hue gradient scrolling every four seconds |
| Chase | Three-pixel selected-color trail advancing every 100 ms |
| Twinkle | Selected-color sparkles every 150 ms with a 750 ms fade |

Every pattern obeys the primary light's ordinary On/Off and brightness controls.
Changing brightness retains the selected pattern and changes its maximum
output. Turning the light off remembers the selection for the current boot;
turning it on restarts the animation. Setting hue, saturation, XY, color
temperature, or a local RGB value selects None and shows that steady color at
the requested brightness.

The active virtual switch is restored from ESP-Matter persistence when the
primary light also restores on. If the light restores off, firmware turns all
pattern switches off instead. The boot cache remains a steady-color fast path,
so a restored animation begins after native Matter state becomes available.

`main.py` runs top to bottom at boot and then drops to the REPL, so `set_color`,
`node`, `endpoint`, `led_count_endpoint`, and `strip` are all still in scope over serial:

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

Factory-reset and recommission after installing the pattern switches or LED
count selector so the controller discovers the device's new endpoint list.

After rebuilding or factory-resetting, use the commissioning artifacts that
match the flashed image.
