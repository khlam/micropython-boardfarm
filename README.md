# MicroPython Boardfarm 
Write MicroPython firmware that behaves the same across all supported microcontroller boards

* **Docker-only** — no local toolchain to install; every compile, flash, and test runs in a container.
* **Reusable packages across projects** — drivers and shared logic in [firmware-packages/](firmware-packages/) keep board-specific quirks tucked away, so calls from your project code stay the same for each MCU board.
* **Write firmware once, run on three chips** — the same project code runs on RP2040, RP2350, and ESP32-S3.
* **Test firmware** — pytest exercises MCU code against MicroPython stubs, so CI doesn't need a physical board.
* **AI-coding-agent-ready** the repo is structured to facilitate AI-assisted development.

Two kinds of code live side by side in this repo:

- **MCU** code runs on the microcontroller under MicroPython — firmware in [projects/](projects/) and shared [firmware-packages/](firmware-packages/) frozen onto the device at compile time.
- **host** code runs on your computer under CPython inside Docker — the [serial_over_web](cpython-packages/serial_over_web/) dashboard, pytest against [micropython_stubs](cpython-packages/micropython_stubs/) (shims for `machine`, `neopixel`, `ujson`, …), and every build toolchain (ARM cross-compiler, ESP-IDF, esptool, MicroPython sources).


## Supported Microcontrollers (MCU)
|   | Board | Notes | Compile & flash |
|:---:|---|---|---|
| <img src="images/rp2040-zero.jpg" alt="RP2040-Zero" width="80"> | RP2040-Zero | No wireless. Onboard WS2812 RGB LED. 264 KB SRAM, no threads. | [Steps →](#rp2040--rp2350) |
| <img src="images/rp2350.jpg" alt="RP2350" width="80"> | RP2350 (Pico 2 W) | WiFi + Bluetooth via the onboard CYW43. Status LED on/off only. | [Steps →](#rp2040--rp2350) |
| <img src="images/esp32-s3.jpg" alt="ESP32-S3-Zero" width="80"> | ESP32-S3-Zero | WiFi + BLE. Onboard WS2812 RGB LED. Native USB-CDC; must be in bootloader mode (BOOT+RESET) before flashing. | [Steps →](#esp32-s3-zero) |


## Supported Peripherals
|   | Chip | Role |
|:---:|---|---|
| <img src="images/MPU6050.jpg" alt="MPU6050" width="80"> | [MPU6050](firmware-packages/mpu6050/) | 6-axis IMU (accel + gyro + temp) |
| <img src="images/VL53L0X.jpg" alt="VL53L0X" width="80"> | [VL53L0X](firmware-packages/vl53l0x/) | Time-of-flight range |
|   | VL53L5X | Time-of-flight range |
|   | VL53L8CX | Time-of-flight range |
|   | PN532 | NFC |
|   | ATGM336H | GPS |
|   | QMC5883P | Magnetometer |
|   | I²C displays | Display |


## Software Dependencies / Stack
- Docker
- MicroPython
- CPython


## Projects
- **[distance-stream](projects/distance-stream/)** — VL53L0X distance → JSON-lines over USB-CDC → FastAPI/WebSocket → Plotly dashboard. See its [README](projects/distance-stream/README.md) for compile, flash, dashboard, and wiring details.
- **[gyro-stream](projects/gyro-stream/)** — MPU6050 accelerometer/gyro/temperature → JSON-lines over USB-CDC → FastAPI/WebSocket → Plotly dashboard with 3D orientation view. See its [README](projects/gyro-stream/README.md) for compile, flash, dashboard, and wiring details.


## Boot LED states
Shared [`boot_status_led`](firmware-packages/boot_status_led/#boot-led-states) package enables uniform LED board-state reporting. 


## Docker commands

All workflows run inside Docker — no host toolchain required. `--build` rebuilds the image when files change.

**From the repo root:**

| Command | Purpose |
|---|---|
| `docker compose up pytest --build --exit-code-from pytest` | Run all tests (everything) |
| `docker compose run --rm pytest <path>` | Run a targeted subset, e.g. `/projects/distance-stream/tests` or `/firmware-packages/vl53l0x/tests -k status` |
| `docker compose run --rm --build uv lock` | Refresh `uv.lock` from `pyproject.toml` |
| `docker compose run --rm uv lock --upgrade` | Bump pinned versions |


## Compile
All commands run from a project directory (e.g. `cd projects/gyro-stream`).


### RP2040 / RP2350
1. Compile the firmware:
   ```
   docker compose up --build pi-compile
   ```
   Produces `outputs/app.rp2040.rp2350.uf2` — one universal UF2 that flashes on both RP2040 and RP2350 (each bootloader skips foreign-family blocks).
2. Put the board in bootloader mode: hold **BOOT** and connect USB (or tap **RESET** while holding BOOT). The board enumerates as a USB mass-storage drive (`RPI-RP2` for RP2040, `RP2350` for RP2350).
3. Copy `outputs/app.rp2040.rp2350.uf2` onto the mounted RP-drive. The board will reboot into the new firmware when the copy completes.


### ESP32-S3-Zero
1. Put the board in bootloader mode: hold **BOOT** and tap **RESET** OR hold **BOOT** and connect USB. Confirm it appears as `/dev/ttyACM0` on the host — the `esp32-flash` service fails fast if the device node is missing. **On macOS, do the [serial bridge setup](#macos-serial-bridge) first** — Docker can't see USB devices there.
2. Compile and flash in one step:
   ```
   docker compose run --rm --build esp32-flash
   ```
   This runs `esp32-compile` first to produce `outputs/app.esp32-s3.bin`, then runs `esptool.py` against `$SERIAL_PORT` (default `/dev/ttyACM0`).
3. Power-cycle to boot into the new firmware.


## macOS: serial bridge
Docker Desktop runs containers inside a Linux VM, and neither it nor Apple's Virtualization.framework can pass a USB-serial device into that VM — so the `/dev:/dev` mount the `viz` and `esp32-flash` services rely on sees nothing on macOS. [`tools/serial-bridge.sh`](tools/serial-bridge.sh) works around this with a full-duplex serial↔TCP relay built from stock tools (`stty`/`cat`/`nc`) — nothing is installed on the host. Set it up **once**, then every project's commands match Linux.

1. In its own terminal, start the bridge and leave it running. It auto-detects the board (`/dev/cu.usbmodem*`) and serves it on TCP `5555`:
   ```sh
   tools/serial-bridge.sh
   ```
2. In your shell profile (`~/.zshrc`), point `SERIAL_PORT` at the bridge so every project picks it up:
   ```sh
   export SERIAL_PORT=socket://host.docker.internal:5555
   ```
   Open a new terminal (or `source ~/.zshrc`) so the variable is set.
3. Run the dashboard or flash exactly as on Linux — both read `SERIAL_PORT`:
   ```sh
   docker compose up --build viz                # reads the board over the bridge
   docker compose run --rm --build esp32-flash  # compiles + flashes over the bridge
   ```
   The bridge carries no DTR/RTS reset line, so flashing requires the board to **already** be in bootloader mode (hold **BOOT**, tap **RESET**); the `esp32-flash` stage passes `--before/--after no_reset` automatically for `socket://` ports.

> RP2040 / RP2350 firmware flashes by drag-copying a UF2 to the mounted bootloader drive, so it needs no serial bridge — only the `esp32-flash` service and the `viz` dashboard use the serial port.

