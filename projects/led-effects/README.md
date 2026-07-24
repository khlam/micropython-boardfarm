# led-effects

MicroPython firmware that drives a 20-LED WS2812B strip in one of two modes:
**random** (the boot default — cycles the four parametric animations rainbow, hue
rotation, breathing, and colour fade, picking the next at random every 200 frames
at ~50 fps) and **solid** (one configured `RRGGBB` colour). A VL53L0X
time-of-flight sensor makes the strip interactive: bring an object into range and
the strip collapses instantly to a live distance gauge; one continuous second
(`RELEASE_MS`) without an object sweeps once and resumes the configured LED mode.
The gauge changes only the LED display.

Separately and continuously from boot, the firmware runs **secure Wi-Fi
provisioning** as a background service: a locked-down WPA2 access point whose
credentials rotate every 10 minutes, joinable by anyone who can read the QR code
on the 128×64 SSD1306 OLED, from where they can set the LED colour or mode via a
tiny no-JavaScript page. The QR is shown **only while the distance gauge is
engaged** and the panel is blank the rest of the time, so the credentials are
legible only to someone standing at the device working the sensor. The AP itself
runs regardless of the gauge. The strip driver and effects are local to this
project, and it ships no dashboard. Pin assignments live in the firmware's
`BOARD` table (dispatched per chip by `os.uname().machine`), so the same firmware
builds for RP2040 (no Wi-Fi — provisioning is an inert no-op), RP2350/Pico 2 W,
and ESP32-S3. The sensor is optional (it only affects the gauge); provisioning
requires a working OLED.

## Layout
```
led-effects/
  firmware/effects.py         rainbow/hue/breathe/fade frame generators
  firmware/main.py            BOARD pin table, LED state machine, gauge + loop, calls emit()
  firmware/provisioning.py    Wi-Fi session lifecycle, OLED QR, HTTP handler + page
  firmware/settings.py        crash-safe dual-slot persistence of the active LED mode
  firmware/strip.py           project-local NeoPixel strip driver
  outputs/                    build artifacts (UF2 + ESP32 bin)
  docker-compose.yaml         pi-compile / esp32-compile / esp32-flash services
```

## Usage

### RP2040 / RP2350
1. Compile the firmware:
   ```bash
   docker compose up --build pi-compile
   ```
   A single Docker build compiles MicroPython for both boards and merges the UF2 outputs into one universal file at [outputs/app.rp2040.rp2350.uf2](outputs/app.rp2040.rp2350.uf2) that flashes correctly on either device.
2. Put the board in [bootloader mode](../microcontrollers.md#bootloader-mode).
3. Drag-and-drop [outputs/app.rp2040.rp2350.uf2](outputs/app.rp2040.rp2350.uf2) onto the mounted USB drive. The board ejects and reboots running the new firmware.

### ESP32-S3
1. Put the board in [bootloader mode](../microcontrollers.md#bootloader-mode) — the service fails fast if `/dev/ttyACM0` isn't present.
2. Compile and flash:
   ```bash
   docker compose run --rm --build esp32-flash
   ```
   Runs `esp32-compile` to produce [outputs/app.esp32-s3.bin](outputs/app.esp32-s3.bin), then immediately flashes it via `esptool.py` running inside the container.

## Notes
- **LED modes.** `random` (boot default) renders the current effect and picks one
  of the four (`rainbow`, `hue_rotate`, `breathe`, `color_fade`) at random with
  `os.urandom(1)` every 200 frames; `solid` renders one configured `RRGGBB` colour
  on all 20 LEDs. The active mode is chosen over Wi-Fi (see Provisioning) and
  persisted. It emits one JSON line per random-effect change (`{"effect": <name>}`),
  the current mode (`{"diag": "led_mode", ...}`), sensor diagnostics
  (`{"diag": "tof_ok"|"no_sensor"|"lock"|"unlock"|...}`), and redacted Wi-Fi status
  (`{"diag": "wifi_up"|"wifi_rotate"|"wifi_config"|"wifi_disabled"|...}` — never a
  credential, QR payload, or CSRF token). There is no dashboard.
- **The distance gauge (LED display only).** The moment a VL53L0X sees an object in
  range, the strip collapses to a soft glow at the mapped position — the first LED is
  `MIN_DISTANCE_MM` (50 mm) and the last is `MAX_DISTANCE_MM` (500 mm, the tunable
  "max measurable distance"). Readings outside that range clamp to the nearest end.
  While locked the glow tracks the object live; once the object is *confirmed*
  out of range for one continuous second (`RELEASE_MS` = 1 s), the gauge sweeps
  across the strip once and the configured LED mode resumes (random/default, or the
  persisted solid colour). Sensor errors preserve the current state — only confirmed
  out-of-range samples advance the release timer. Gauge entry and exit change the
  LEDs and draw or blank the OLED QR (below); they never start or stop the AP. All
  are constants at the top of [firmware/main.py](firmware/main.py).
- **The OLED.** A 128×64 I²C SSD1306 at address `0x3C`, blank except while the
  gauge is locked. Locking the gauge draws **only** the QR for the currently valid
  credentials — no text, prompt, or startup message — and releasing it blanks the
  panel again; the Version-2-L code is rendered at 2× module scale in a 64×64
  frame with a seven-pixel light border, using the OLED's full height. Each
  transition costs roughly one frame of I²C flush. Rotation redraws the QR if it
  is on screen at the time. Initialisation is retried three
  times; if the display remains absent or faulty, an `oled_disabled` diagnostic is
  emitted, provisioning is skipped, and the effects and gauge continue. **Without a
  working VL53L0X the gauge never locks, so the QR is never shown and the AP,
  though running, cannot be joined.**

## Provisioning
- **Continuous, from boot.** After clearing any stale AP (`wifi.quiesce()`), a
  supported Wi-Fi port with a working OLED brings up a WPA2-PSK/CCMP access point
  (`LFX-` + 2 hex, with an 8-character hexadecimal password, channel 6,
  `192.168.4.1/24`, alias `led-effects.test`). The AP
  broadcasts and accepts a client **continuously for the device's entire uptime** —
  not only during a deliberate provisioning window — but its credentials are
  displayed only while the gauge is locked.
- **Rotation.** Every 10 minutes the credentials rotate: fresh SSID, password, and
  CSRF token from one radio-backed `os.urandom` read, the AP restarts under them,
  and any connected client is dropped (it rejoins after reading the new QR). If the
  QR is on screen when a rotation lands it is redrawn immediately; if it is not,
  the next gauge lock draws the current one. Nothing is persisted about the
  session, so boot, crash, reset, and watchdog recovery always start from fresh
  credentials and never resume old ones.
- **Routes.** `GET /` serves one self-contained, no-JavaScript, no-CSS page with a
  text field for an uppercase `RRGGBB` colour and separate POST forms. `POST /color`
  sets a solid colour; `POST /random` returns to random mode. Both require a
  matching CSRF token, an exact same-origin host, and
  `Content-Type: application/x-www-form-urlencoded`; every response carries a strict
  `Content-Security-Policy` and no-store/nosniff/no-referrer headers.
- **Persistence.** The active mode is stored as a small JSON record with a
  monotonic generation, written alternately to `/led-effects-0.json` and
  `/led-effects-1.json` via a temp-file-and-rename commit (flush + `os.sync`), so a
  power loss at any step keeps a valid generation. On boot the newest valid record
  wins; a missing or corrupt pair falls back to random mode.
- **Accepted risk.** Anyone who can see the OLED QR can configure the LEDs until
  the next rotation. Gating the QR on the gauge shrinks the window in which the
  credentials are *readable*, but it does not revoke them: whoever has read them
  keeps full control until the next rotation, whatever the gauge and OLED are
  doing, and the AP remains discoverable the whole time. On ports
  that cannot enforce the one-client limit or client isolation (the Pico 2 W does
  not; the ESP32-S3 enforces `max_clients=1` where the port allows), **more than one
  client may control the LEDs at once**, and every associated client is fully
  trusted. On the ESP32-S3 the AP is also started and stopped once per boot, before
  any credentials exist, to satisfy an ESP-IDF ordering rule — a sub-beacon-interval
  window advertising the default SSID openly; see the
  [wifi package notes](../../firmware-packages/wifi/README.md#notes). The plain
  RP2040 has no radio and never starts an AP.
- The strip is fixed at 20 LEDs (`LED_COUNT` in [firmware/main.py](firmware/main.py));
  change it there and recompile to drive a longer strip.
- Pins are project wiring — they live in the `BOARD` table in
  [firmware/main.py](firmware/main.py), dispatched per chip by
  `os.uname().machine`. The data pin reaches the strip as `Strip(count, pin=...)`;
  the I²C pins reach the sensor as `VL53L0X(sda=, scl=, int_pin=)`, which opens its
  own bit-banged soft-I²C bus internally and attaches a falling-edge interrupt to
  the `INT` pin so reads fire on the sensor's "new sample ready" signal instead of
  blocking. The SSD1306 driver opens a separate software-I²C bus on the OLED pins.

  | Board         | Strip data | VL53 SDA | VL53 SCL | VL53 INT | OLED SDA | OLED SCL |
  | ------------- | ---------- | -------- | -------- | -------- | -------- | -------- |
  | RP2040-Zero   | `GP15`     | `GP0`    | `GP1`    | `GP4`    | `GP2`    | `GP3`    |
  | RP2350        | `GP15`     | `GP0`    | `GP1`    | `GP4`    | `GP2`    | `GP3`    |
  | ESP32-S3-Zero | `GPIO7`    | `GPIO1`  | `GPIO2`  | `GPIO3`  | `GPIO8`  | `GPIO9`  |

  Every board drives the strip from a dedicated GPIO, separate from its on-board
  status indicator. RP2040-Zero and ESP32-S3-Zero use WS2812 LEDs on `GP16` and
  `GPIO21`; RP2350 uses a single-colour LED through CYW43 `WL_GPIO0`. None is
  wired into the strip chain or counted among the effects LEDs.
- LED indication is chip-aware — see the [Boot LED states table](../../firmware-packages/boot_status_led/README.md#boot-led-states)
  in the boot_status_led README.

## Hardware

| RP2040-Zero board | RP2350 | ESP32-S3-Zero |
|:---:|:---:|:---:|
| <img src="../../images/rp2040-zero.jpg" alt="RP2040-Zero board" width="220"> | <img src="../../images/rp2350.jpg" alt="RP2350" width="220"> | <img src="../../images/esp32-s3.jpg" alt="ESP32-S3-Zero" width="220"> |

## Wiring

A WS2812B strip needs three connections — **5V** (VCC), **GND**, and **DIN**
(serial data in). Wire `DIN` to the input end of the strip; the arrows printed on
the strip point *away* from it. Common ground is mandatory: board `GND`, strip
`GND`, and any external 5V supply must share a ground or the data line has no
reference and the strip flickers or stays dark.

The VL53L0X breakout and four-pin SSD1306 module use separate **SDA** and
**SCL** pairs but share **3V3** and **GND**. Both are optional: leave either one
off and the animations still run. Power both from the board's 3.3 V rail:

| Peripheral pin | RP2040-Zero | RP2350 | ESP32-S3-Zero |
| -------------- | ----------- | ------ | ------------- |
| OLED VCC        | `3V3`       | `3V3`  | `3V3`         |
| OLED GND        | `GND`       | `GND`  | `GND`         |
| OLED SDA        | `GP2`       | `GP2`  | `GPIO8`       |
| OLED SCL        | `GP3`       | `GP3`  | `GPIO9`       |

| VL53L0X pin    | RP2040-Zero | RP2350 | ESP32-S3-Zero |
| -------------- | ----------- | ------ | ------------- |
| VIN            | `3V3`       | `3V3`  | `3V3`         |
| GND            | `GND`       | `GND`  | `GND`         |
| SDA            | `GP0`       | `GP0`  | `GPIO1`       |
| SCL            | `GP1`       | `GP1`  | `GPIO2`       |
| `GPIO1` (INT)  | `GP4`       | `GP4`  | `GPIO3`       |

> **The `INT` wire is required for the gauge.** The last row is the breakout's
> **interrupt output** — silk-labelled `GPIO1` on the module, unrelated to the
> MCU pin also named `GPIO1` on the ESP32-S3. It drives the sensor's "new sample
> ready" signal into the MCU `int_pin` (configured input, pull-up, active-low), so
> the firmware reads on the falling edge instead of blocking. Leave it off and no
> samples reach the gauge — the strip runs its animations but never locks. (The
> whole sensor stays optional: omit the module and the animations still run.)

> ⚠️ **Power both I²C modules from `3V3`, not the 5V strip rail.** These MCUs'
> GPIOs are not 5V-tolerant, and typical breakouts pull their I²C lines up to
> their supply. A 5 V supply can therefore idle SDA/SCL at 5 V and damage the
> board. Share a common GND across the board, strip, sensor, and OLED.

### RP2040-Zero

```
                                   ┌─── USB-C ───┐
                              ┌────┴─────────────┴────┐
                              │                       │
         WS2812B 5V ◄───  5V ─┤                       ├─ 0 ───► VL53L0X SDA
 OLED/VL53/STRIP GND ◄── GND ─┤                       ├─ 1 ───► VL53L0X SCL
      OLED/VL53 VCC ◄─── 3V3 ─┤                       ├─ 2 ───► OLED SDA
                          29 ─┤                       ├─ 3 ───► OLED SCL
                          28 ─┤                       ├─ 4 ───► VL53L0X INT
                          27 ─┤  [BOOT] (●) [RESET]   ├─ 5
                          26 ─┤        WS2812         ├─ 6
        WS2812B DIN ◄───  15 ─┤        on GP16        ├─ 7
                          14 ─┤                       ├─ 8
                              │    RP2040 BOARD       │
                              │                       │
                              └─┬────┬────┬────┬────┬─┘
                                │    │    │    │    │
                                13   12   11   10   9
```

The strip's `DIN` goes to `GP15`, leaving the on-board WS2812 (boot status LED)
on `GP16` free. The VL53L0X uses `GP0`/`GP1` for I²C and `GP4` for its `INT`
(new-sample-ready) line; the OLED uses `GP2`/`GP3`. They share `3V3` and GND.

### ESP32-S3-Zero

```
                                    ┌───── USB-C ─────┐
                               ┌────┴─────────────────┴────┐
     WS2812B 5V ◄── 5V / VBUS ─┤                           ├─ GPIO43 / TX
  OLED/VL53/STRIP GND ◄── GND ─┤                           ├─ GPIO44 / RX
     OLED/VL53 VCC ◄─ 3V3 OUT ─┤                           ├─ GPIO13
        VL53L0X SDA ◄── GPIO1 ─┤                           ├─ GPIO12
        VL53L0X SCL ◄── GPIO2 ─┤                           ├─ GPIO11
        VL53L0X INT ◄── GPIO3 ─┤   [BOOT]       [RESET]    ├─ GPIO10
                        GPIO4 ─┤    GPIO0          EN      ├─ GPIO9 ───► OLED SCL
                        GPIO5 ─┤                           ├─ GPIO8 ───► OLED SDA
                        GPIO6 ─┤    WS2812: GPIO21         ├─ GPIO7 ───► WS2812B DIN
                               │                           │
                               └───────────────────────────┘
```

The strip's `DIN` goes to `GPIO7`, leaving the on-board WS2812 (boot status LED)
on `GPIO21` free — the on-board pixel is never part of the strip chain. The
VL53L0X uses `GPIO1`/`GPIO2` for I²C and `GPIO3` for its `INT` (new-sample-ready)
line; the OLED uses `GPIO8`/`GPIO9`. They share `3V3` and GND.

### RP2350

```
                                          ┌──── USB ────┐
                              ┌───────────┴─────────────┴───────────┐
                              │                                     │
        VL53L0X SDA ◄───   0 ─┤                                     ├─ VBUS ────► WS2812B 5V
        VL53L0X SCL ◄───   1 ─┤                                     ├─ VSYS
        WS2812B GND ◄─── GND ─┤                                     ├─ GND
           OLED SDA ◄───   2 ─┤                                     ├─ 3V3_EN
           OLED SCL ◄───   3 ─┤                                     ├─ 3V3 ────► I²C VCC
        VL53L0X INT ◄───   4 ─┤                                     ├─ ADC_VREF
                           5 ─┤                                     ├─ 28
                         GND ─┤   [BOOTSEL] (●) LED on WL_GPIO0     ├─ AGND
                           6 ─┤                                     ├─ 27
                           7 ─┤                                     ├─ 26
                           8 ─┤      RP2350                         ├─ RUN
                           9 ─┤                                     ├─ 22
                         GND ─┤                                     ├─ GND
                          10 ─┤                                     ├─ 21
                          11 ─┤                                     ├─ 20
                          12 ─┤                                     ├─ 19
                          13 ─┤                                     ├─ 18
                         GND ─┤                                     ├─ GND
                          14 ─┤                                     ├─ 17
        WS2812B DIN ◄───  15 ─┤                                     ├─ 16
                              │                                     │
                              └─────────────────────────────────────┘
```

`VBUS` is the 5 V USB rail. The strip's `DIN` goes to `GP15`, separate from the
single-colour boot status LED on CYW43 `WL_GPIO0`. The VL53L0X uses `GP0`/`GP1`
for I²C and `GP4` for its `INT` (new-sample-ready) line; the OLED uses
`GP2`/`GP3`. They share `3V3` and GND.

**Power**
- A WS2812B LED draws up to ~60 mA at full white. A handful of LEDs can run from
  the board's `5V`/`VBUS` pin over USB; for longer strips feed the strip from a
  dedicated 5V supply and still tie all grounds together.
- These boards drive `DIN` at 3.3 V logic, which is reliable for short leads. For
  long runs, add a 5V level shifter on the data line.
- Power the VL53L0X and OLED from the board's `3V3` pin, **not** the 5V strip
  rail: the GPIOs are not 5V-tolerant and breakout I²C pull-ups commonly sit on
  their supply rail. Their `GND` pins tie into the strip's common ground.
