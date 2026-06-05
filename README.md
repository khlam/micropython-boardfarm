# MicroPython Boardfarm

- Shared host [cpython-packages](cpython-packages/README.md)
- Shared Microcontroller (**MCU**) [firmware-packages](firmware-packages/README.md)
- [projects](projects/README.md)
---

Develop embedded IoT hardware and software in parallel.
AI co-develops the software from human direction and diagnosis of the embedded system. 
Write-once library code runs across different MCUs and shared peripherals.

|   | Board | Notes | Compile & flash |
|:---:|---|---|---|
| <img src="images/rp2040-zero.jpg" alt="RP2040-Zero" width="80"> | RP2040-Zero | No wireless. Onboard WS2812 RGB LED. 264 KB SRAM, no threads. | [Steps →](projects/microcontrollers.md#compile--flash) |
| <img src="images/rp2350.jpg" alt="RP2350" width="80"> | RP2350 (Pico 2 W) | WiFi + Bluetooth via the onboard CYW43. Status LED on/off only. | [Steps →](projects/microcontrollers.md#compile--flash) |
| <img src="images/esp32-s3.jpg" alt="ESP32-S3-Zero" width="80"> | ESP32-S3-Zero | WiFi + BLE. Onboard WS2812 RGB LED. Native USB-CDC; must be in bootloader mode (BOOT+RESET) before flashing. | [Steps →](projects/microcontrollers.md#compile--flash) |


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
Mac Users: see [serial bridge setup](tools/serial-bridge/serial-bridge.md#macos-serial-bridge).

**From the repo root:**

| Command | Purpose |
|---|---|
| `docker compose up pytest --build --exit-code-from pytest` | Run all tests (everything) |
| `docker compose run --rm pytest <path>` | Run a targeted subset, e.g. `/projects/distance-stream/tests` or `/firmware-packages/vl53l0x/tests -k status` |
| `docker compose run --rm --build uv lock` | Refresh `uv.lock` from `pyproject.toml` |
| `docker compose run --rm uv lock --upgrade` | Bump pinned versions |

