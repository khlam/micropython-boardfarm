# clock

A GPS-synced wall clock with a 16×32 MAX7219 LED matrix (two 8×32 panels
daisy-chained in series on one SPI bus, sharing 5 V and GND). MicroPython firmware reads
UTC date/time and longitude from an ATGM336H GPS over UART (NMEA RMC), derives a
fixed UTC offset from the longitude (`round(lon/15)`, since MicroPython has no
timezone database), converts to local time, sets the onboard RTC, and drives the
matrix over SPI. The UART and SPI buses are independent: one cooperative loop pumps the GPS
(non-blocking `readline`) and advances the display every tick while the RTC keeps
time between GPS bursts — neither bus blocks the other. A host FastAPI service
fans the per-fix JSON lines out over a WebSocket and serves a live clock
dashboard.

The display alternates:

- **Time** — 12-hour, bold font, blinking colon, AM/PM.
- **Day of week** — the weekday name (wiggles if wider than 32 px).

Board-specific pin maps live in `firmware/main.py`'s `BOARD` wiring table, so the
packages remain board-agnostic and the firmware builds for RP2040, RP2350, and ESP32-S3.

## Layout
```
clock/
  firmware/main.py            chip-agnostic GPS→RTC→display loop, calls emit()
  viz/static/index.html       live clock panel (time, day, longitude, UTC offset)
  tests/                      host pytest for the run() behaviour
  outputs/                    build artifacts (UF2 + ESP32 bin)
  docker-compose.yaml         pi-compile / esp32-compile / esp32-flash / viz services
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

### Web dashboard
With the board plugged in (`/dev/ttyACM0`):
```bash
docker compose up --build viz
```
Open `http://localhost:18501`. The connection pill turns green when the serial
port is open, and a second pill shows `FIX` / `NO FIX`. Once the GPS has a fix the
panel mirrors the matrix — the local time, AM/PM, day of week — alongside the
detected longitude, derived UTC offset, and the age of the last fix. The
dashboard auto-reconnects if you unplug and replug the board.

## Notes
- The firmware skips any I²C scan — it opens the UART (GPS) and SPI (display)
  buses directly. The LED goes white (boot) → cyan (opening buses) → green
  (running); an init failure flashes magenta and retries from white.
- The display shows `WAITING FOR GPS` (wiggled so the panel proves it is alive)
  until the first checksum-valid RMC sentence carrying UTC time, date, and
  longitude arrives. The longitude sets a fixed whole-hour offset
  (`round(lon/15)`); there is no DST or timezone-boundary handling.
- Each fix emits one JSON line:
  `{"fix": true, "lon": <deg>, "offset_h": <int>, "local": "<ISO local time>", "day": "<weekday>", "t": <ms>}`.
  UART/parse faults emit `{"diag": "read_err"}` and briefly turn the LED red
  before returning to green; an init failure emits `{"diag": "init_err"}`.
- LED indication is chip-aware — see the [Boot LED states table](../../firmware-packages/boot_status_led/README.md#boot-led-states)
  in the boot_status_led README.

## Hardware

| RP2040-Zero board | RP2350 | ESP32-S3-Zero | ATGM336H GPS module | MAX7219 16×32 matrix |
|:---:|:---:|:---:|:---:|:---:|
| <img src="../../images/rp2040-zero.jpg" alt="RP2040-Zero board" width="220"> | <img src="../../images/rp2350.jpg" alt="RP2350" width="220"> | <img src="../../images/esp32-s3.jpg" alt="ESP32-S3-Zero" width="220"> | ATGM336H | 2× MAX7219 (FC-16) |

## Wiring

The clock uses two buses: **UART** to the GPS and a single **SPI** chain to the
LED matrices. The two 8×32 panels are daisy-chained in series — the MCU drives
the top panel, whose output feeds the bottom panel — and the `max7219` driver
presents the cascade as one 16×32 surface (top panel = rows 0-7, bottom panel =
rows 8-15). CLK, DIN, and CS run from the MCU to the top panel only; the bottom
panel takes DIN from the top panel's DOUT and shares CLK/CS down the chain. The
authoritative pin map lives in `main.py`'s `BOARD` wiring table; the per-board
diagrams below mirror it.

### ATGM336H GPS module

```
                              ┌─────────────────────┐
                              │   ┌──────────────┐  │
                              │   │  ATGM336H IC │  │
                              │   │      ◎       │  │
                              │   └──────────────┘  │
                              │                     │
                5V ────► VCC ─┤                     │
               GND ────► GND ─┤   BREAKOUT BOARD    │
               MCU RX ◄── TX ─┤                     │
               MCU TX ────► RX┤  (optional — only   │
                              │   needed to send     │
                              │   NMEA commands)     │
                              └─────────────────────┘
```

**Power:** the ATGM336H module includes an onboard 3.3 V LDO, so **VCC accepts
3.3–5 V** — the 5 V USB rail is fine. The module's UART I/O is 3.3 V logic, which
is safe for all three MCU targets. Only the GPS TX → MCU RX connection is required
for receiving NMEA sentences; MCU TX → GPS RX is optional.

### MAX7219 16×32 matrix (two 8×32 panels daisy-chained in series)

```
                              ┌──────────────────────────────┐
                              │  ███ 8×32 MAX7219 MATRIX ███ │  top panel — cabled to the MCU
                5V ────► VCC ─┤██████████████████████████████│
               GND ────► GND ─┤                              │
           MCU DIN ────► DIN ─┤  IN ►   FC-16 MODULE   ► OUT ├─┐
            MCU CS ────► CS  ─┤                              │ │  OUT header carries
           MCU CLK ────► CLK ─┤                              │ │  5 V · GND · DOUT · CS · CLK
                              └──────────────────────────────┘ │
                              ┌──────────────────────────────┐ │
                              │  ███ 8×32 MAX7219 MATRIX ███ │ │  bottom panel — daisy-chained
                       VCC ◄──┤██████████████████████████████│ │
                       GND ◄──┤                              │ │
                       DIN ◄──┤  IN ►   FC-16 MODULE         ├─┘  (top DOUT → bottom DIN;
                       CS  ◄──┤                              │     CS / CLK shared down chain)
                       CLK ◄──┤                              │
                              └──────────────────────────────┘
```

**Power:** the MAX7219 is a 5 V part — power both panels' VCC from the 5 V USB
rail; the daisy-chain ribbon carries 5 V / GND from the top panel to the bottom.
The MCU's 3.3 V SPI drives only the top panel's DIN / CS / CLK directly — fine at
1 MHz over short leads — and the bottom panel is driven entirely through the top
panel's DOUT. Eight cascaded MAX7219s can draw well over 1 A at full brightness,
so use an external 5 V supply for sustained use.

### RP2040-Zero

```
                                   ┌─── USB-C ───┐
                              ┌────┴─────────────┴────┐
                              │                       │
   GPS · MATRIX VCC ◄───  5V ─┤                       ├─ 0  ────► GPS RX (opt.)
   GPS · MATRIX GND ◄─── GND ─┤                       ├─ 1  ◄──── GPS TX
                         3V3 ─┤                       ├─ 2
                          29 ─┤                       ├─ 3
    TOP MATRIX CS  ◄───── 28 ─┤                       ├─ 4
    TOP MATRIX DIN ◄───── 27 ─┤  [BOOT] (●) [RESET]   ├─ 5
    TOP MATRIX CLK ◄───── 26 ─┤        WS2812         ├─ 6  (free)
                          15 ─┤        on GP16        ├─ 7  (free)
                          14 ─┤                       ├─ 8  (free)
                              │    RP2040 BOARD       │
                              │                       │
                              └─┬────┬────┬────┬────┬─┘
```

GP1 is UART0 RX (data flows from GPS into the MCU); GP0 is UART0 TX and is
optional. The MAX7219 chain runs on SPI1 — **CLK=GP26, DIN=GP27, CS=GP28** — to
the top panel; the bottom panel daisy-chains off the top panel's output header,
so it needs no MCU pins (GP6–GP8 are free for other use). Pins
GP9–GP13 are reserved (underside castellated pads) and must not be used. The
on-board WS2812 is driven by GP16 — no external wiring required.

### ESP32-S3-Zero

```
                                   ┌─── USB-C ───┐
                              ┌────┴─────────────┴────┐
                              │                       │
   GPS · MATRIX VCC ◄───  5V ─┤                       ├─ 13 ────► GPS RX (opt.)
   GPS · MATRIX GND ◄─── GND ─┤                       ├─ 12 ◄──── GPS TX
                         3V3 ─┤                       ├─ 11 (free)
                           1 ─┤                       ├─ 10 (free)
                           2 ─┤                       ├─ 9  (free)
                           3 ─┤  [BOOT] (●) [RESET]   ├─ 8
                           4 ─┤        WS2812         ├─ 43
     TOP MATRIX CLK ◄───── 5 ─┤        on GPIO21      ├─ 44
     TOP MATRIX DIN ◄───── 6 ─┤                       ├─ 14
     TOP MATRIX CS  ◄───── 7 ─┤   ESP32-S3-Zero       ├─ 15
                              │                       │
                              └─┬────┬────┬────┬────┬─┘
```

GPIO12 is UART1 RX (data flows from GPS into the MCU); GPIO13 is UART1 TX and is
optional. The MAX7219 chain runs on SPI1 — **CLK=GPIO5, DIN=GPIO6, CS=GPIO7** —
to the top panel; the bottom panel daisy-chains off the top panel's output
header, so it needs no MCU pins (GPIO9–GPIO11 are free for other use).
The on-board WS2812 is driven by GPIO21 — no external wiring required.

### RP2350

```
                                          ┌──── USB ────┐
                              ┌───────────┴─────────────┴───────────┐
                              │                                     │
                           0 ─┤                                     ├─ VBUS ──► GPS · MATRIX VCC
                           1 ─┤                                     ├─ VSYS
   GPS · MATRIX GND ◄─── GND ─┤                                     ├─ GND
                           2 ─┤                                     ├─ 3V3_EN
                           3 ─┤                                     ├─ 3V3
        GPS RX (opt.) ◄─── 4 ─┤                                     ├─ ADC_VREF
               GPS TX ───► 5 ─┤                                     ├─ 28
                         GND ─┤   [BOOTSEL] (●) LED on WL_GPIO0     ├─ AGND
                           6 ─┤                                     ├─ 27
                           7 ─┤                                     ├─ 26
                           8 ─┤      RP2350                         ├─ RUN
        TOP MATRIX CS ◄─── 9 ─┤                                     ├─ 22
                         GND ─┤                                     ├─ GND
      TOP MATRIX CLK ◄─── 10 ─┤                                     ├─ 21
      TOP MATRIX DIN ◄─── 11 ─┤                                     ├─ 20
                          12 ─┤                                     ├─ 19
                          13 ─┤                                     ├─ 18
                         GND ─┤                                     ├─ GND
                          14 ─┤                                     ├─ 17
                          15 ─┤                                     ├─ 16
                              │                                     │
                              └─────────────────────────────────────┘
```

VBUS is the 5 V USB rail. GP5 is UART1 RX; GP4 is UART1 TX (optional). The
MAX7219 chain runs on SPI1 — **CS=GP9, CLK=GP10, DIN=GP11** — to the top panel;
the bottom panel daisy-chains off the top panel's output header, so it needs no
MCU pins (GP6–GP8 are free for other use).

## Packages used

`atgm336h` (GPS UART), `nmea` (sentence parsing), `tz_offset` (UTC→local),
`max7219` (display driver + fonts + display-cycle), `boot_status_led` (status LED).
