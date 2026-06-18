# clock

A GPS-synced wall clock on an 8x32 MAX7219 LED matrix.

An ATGM336H GPS provides UTC date/time and longitude over UART (NMEA RMC). The
firmware derives a fixed UTC offset from the longitude (`round(lon/15)`, since
MicroPython has no timezone database), converts to local time, sets the onboard
RTC, and drives the display over SPI. The two buses are independent: one
cooperative loop pumps the GPS (non-blocking `readline`) and advances the display
every tick, while the RTC keeps time between GPS bursts — neither bus blocks the
other.

The display alternates:

- **Time** — 12-hour, bold font, blinking colon, AM/PM.
- **Day of week** — the weekday name (wiggles if wider than 32px).

All board-specific pins live in the package backends (`atgm336h`, `max7219`), so
`firmware/main.py` is board-agnostic and builds for RP2040, RP2350, and ESP32-S3.

## Build & run

From this directory:

```
docker compose up --build pi-compile     # RP2040 + RP2350 -> outputs/app.rp2040.rp2350.uf2
docker compose up --build esp32-compile  # ESP32-S3 -> outputs/app.esp32-s3.bin
docker compose up --build viz            # dashboard on http://localhost:18502
```

## Packages used

`atgm336h` (GPS UART), `nmea` (sentence parsing), `tz_offset` (UTC→local),
`max7219` (display driver + fonts + display-cycle), `boot_status_led` (status LED).
