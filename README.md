# MicroPython Boardfarm
An open-source experimental framework to develop embedded IoT hardware and software in parallel.


AI co-develops the software from human direction and diagnosis of the embedded system.


## Important links
- Shared host [cpython-packages](cpython-packages/README.md)
- Shared Microcontroller (**MCU**) [firmware-packages](firmware-packages/README.md)
- [projects](projects/README.md)

## Supported Devices

### Microcontrollers (MCU)
Write-once library code runs across different microcontroller architectures.

|   | Board | Notes | Compile & flash |
|:---:|---|---|---|
| <img src="images/rp2040-zero.jpg" alt="RP2040-Zero" width="80"> | RP2040-Zero | No wireless. Onboard WS2812 RGB LED. 264 KB SRAM, no threads. | [Steps →](#compile--flash) |
| <img src="images/rp2350.jpg" alt="RP2350" width="80"> | RP2350 (Pico 2 W) | WiFi + Bluetooth via the onboard CYW43. Status LED on/off only. | [Steps →](#compile--flash) |
| <img src="images/esp32-s3.jpg" alt="ESP32-S3-Zero" width="80"> | ESP32-S3-Zero | WiFi + BLE. Onboard WS2812 RGB LED. Native USB-CDC; must be in bootloader mode (BOOT+RESET) before flashing. | [Steps →](#compile--flash) |


### Supported Peripherals
Write-once library code runs across different shared peripherals.

|   | Chip | Role |
|:---:|---|---|
| <img src="images/MPU6050.jpg" alt="MPU6050" width="80"> | [MPU6050](firmware-packages/mpu6050/) | 6-axis IMU (accel + gyro + temp) |
| <img src="images/VL53L0X.jpg" alt="VL53L0X" width="80"> | [VL53L0X](firmware-packages/vl53l0x/) | Time-of-flight range |
|   | [VL53L5CX](firmware-packages/vl53l5cx/) | Time-of-flight range (8×8 multizone) |
|   | VL53L8CX | Time-of-flight range |
|   | PN532 | NFC |
|   | ATGM336H | GPS |
|   | QMC5883P | Magnetometer |
|   | I²C displays | Display |


## Docker commands

All workflows run inside Docker — no local toolchain to install; every compile, flash, and test runs in a container. `--build` rebuilds the image when files change.
Mac Users: see [serial bridge setup](#macos-serial-bridge).

**From the repo root:**

| Command | Purpose |
|---|---|
| `docker compose up pytest --build --exit-code-from pytest` | Run all tests (everything) |
| `docker compose run --rm pytest <path>` | Run a targeted subset, e.g. `/projects/distance-stream/tests` or `/firmware-packages/vl53l0x/tests -k status` |
| `docker compose run --rm --build uv lock` | Refresh `uv.lock` from `pyproject.toml` |
| `docker compose run --rm uv lock --upgrade` | Bump pinned versions |


## Compile & flash
Compile and flash run **per project** — `cd projects/<project>` first, then follow that project's README, which carries the full step-by-step for every board alongside its dashboard and wiring. The command summary lives in [projects/README.md](projects/README.md#usage).

> RP2040 / RP2350 firmware flashes by drag-copying a UF2 onto the mounted bootloader drive, so it needs no serial bridge — only the `esp32-flash` service and the `viz` dashboard use the serial port. **On macOS, do the [serial bridge setup](#macos-serial-bridge) first** — Docker can't see USB devices there.

## Bootloader mode
Put the board in bootloader mode before flashing.

| Board | How | Result |
|---|---|---|
| RP2040-Zero | Hold **BOOT** and connect USB (or tap **RESET** while holding **BOOT**) | Mounts as USB drive `RPI-RP2` — drag the UF2 onto it |
| RP2350 | Hold **BOOT** and connect USB (or tap **RESET** while holding **BOOT**) | Mounts as USB drive `RP2350` — drag the UF2 onto it |
| ESP32-S3-Zero | Hold **BOOT** and tap **RESET**, or hold **BOOT** and connect USB | Appears as `/dev/ttyACM0`; the `esp32-flash` service fails fast if the node is missing |


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

