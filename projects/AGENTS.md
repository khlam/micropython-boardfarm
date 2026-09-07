# projects

## Design

Each project (`projects/<project>/`) contains firmware that builds for every chip it supports. Pin assignments — which GPIOs carry SPI, I2C, UART, and device chip-selects — live in the project's `main.py` as a `BOARD` table of **plain pin numbers** dispatched by `os.uname().machine` at import time, because different projects wire their boards differently and the mapping is pure project-specific configuration.

Project wiring belongs in `projects/<project>/firmware/main.py`. Reusable hardware behavior belongs in `firmware-packages/`.

Keep independent failure domains independent. A dashboard or Matter publication failure must not silently redefine sensor state unless the product contract says it should.

`<project>` denotes any subdirectory under `projects/` — list it with `ls projects/` to see what's currently present, and substitute the real name when running commands.

## Routing

Before changing anything, identify the area you're touching:

| Area | Path | Key files |
| --- | --- | --- |
| Entry point | `projects/<project>/firmware/` | `main.py` — BOARD pin table, sensor init/retry, JSON streaming loop |
| Matter occupancy sensor | `projects/matter-radar-sensor/` | `firmware/main.py` — calls `radar.detect()` for whichever radar is wired to the shared UART, then translates its target reports into a read-only Occupancy Sensor endpoint, with a second virtual Dimmable Light endpoint whose level maps linearly to the 0–10 minute hold after the last target; also serves its own dashboard over `httpd` once Matter has a network address |
| Viz backend | `projects/<project>/viz/` | `app.py` — serial reader + WebSocket broadcaster on `/ws` |
| Viz dashboard | `projects/<project>/viz/static/` | `index.html` — Plotly line chart + numeric readout |
| Project compose | `projects/<project>/` | `docker-compose.yaml` — `build.context: ../..` → repo root |
| RP firmware output | `projects/<project>/outputs/` | `app.rp2040.rp2350.uf2` — Universal UF2 for RP2040 + RP2350 |
| ESP32 firmware output | `projects/<project>/outputs/` | `app.esp32-s3.bin` — ESP-IDF `.bin`, flashed by `esp32-flash` service |

## Universal UF2 vs ESP32 bin †

| Artifact | Detail |
| --- | --- |
| `outputs/app.rp2040.rp2350.uf2` | covers RP2040 and RP2350 only — each bootloader skips foreign-family blocks. |
| `outputs/app.esp32-s3.bin` | is a separate ESP-IDF image flashed via `esptool.py`. Never concatenate them. |

---

† Project-specific quirk — e.g. behavior that differs between the MicroPython firmware runtime and the CPython host-test environment.
