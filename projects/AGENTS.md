# projects

## Design

Each project (`projects/<project>/`) contains firmware that builds for every chip it supports. Pin assignments — which GPIOs carry SPI, I2C, UART, and device chip-selects — live in the project's `main.py` as a `BOARD` table of **plain pin numbers** dispatched by `os.uname().machine` at import time, because different projects wire their boards differently and the mapping is pure project-specific configuration.

Project wiring belongs in `projects/<project>/firmware/main.py`. Reusable hardware behavior belongs in `firmware-packages/`.

Keep independent failure domains independent. A dashboard or Matter publication failure must not silently redefine sensor state unless the product contract says it should.

`<project>` denotes any subdirectory under `projects/` — list it with `ls projects/` to see what's currently present, and substitute the real name when running commands.

## Universal UF2 vs ESP32 bin †

| Artifact | Detail |
| --- | --- |
| `outputs/app.rp2040.rp2350.uf2` | covers RP2040 and RP2350 only — each bootloader skips foreign-family blocks. |
| `outputs/app.esp32-s3.bin` | is a separate ESP-IDF image flashed via `esptool.py`. Never concatenate them. |

---

† Project-specific quirk — e.g. behavior that differs between the MicroPython firmware runtime and the CPython host-test environment.
