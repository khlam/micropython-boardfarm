# firmware-packages
Shared MCU packages. At firmware compile time, each `<pkg>/` is frozen into `ports/rp2/modules/<pkg>/` or `ports/esp32/modules/<pkg>/`.


## Package Layout
```
<pkg>/
  <pkg>/            MCU firmware code (frozen onto the device)
  tests/            host pytest with stubbed machine/neopixel/ujson
  pyproject.toml    uv workspace member metadata
  README.md         usage, public API, chip-dispatch rationale
```


## Packages
| Package | What it does |
|---|---|
| [atgm336h](atgm336h/) | Driver for the ATGM336H GNSS module: reads NMEA sentences over UART. |
| [boot_button](boot_button/) | Board-agnostic BOOT button as a debounced press callback: GPIO0 IRQ on the ESP32-S3, BOOTSEL polling on the RP chips. |
| [boot_status_led](boot_status_led/) | Boot/runtime indicator LED state machine. |
| [httpd](httpd/) | On-device HTTP page server and WebSocket broadcast for board-hosted dashboards. |
| [i2c_bus](i2c_bus/) | `soft_i2c(sda, scl)` / `hard_i2c(bus_id, sda, scl)` bus factories plus `DeviceNotFoundError`; consumed only by drivers, never by projects. |
| [matter](matter/) | Reusable MicroPython endpoint API over native ESP-Matter. |
| [max7219](max7219/) | Driver for two cascaded MAX7219 8×32 panels stacked into one 16×32 matrix, exposed as a `pixel_display.Display`. |
| [mpu6050](mpu6050/) | Driver for the InvenSense MPU family IMU (MPU6050 / MPU6500 / MPU9250)|
| [nmea](nmea/) | Pure NMEA-0183 sentence parsing — checksum, GSV/GGA/RMC fields. No hardware dependency. |
| [pixel_display](pixel_display/) | Geometry check and brightness policy between packed `pixel_frame` frames and a matrix backend. |
| [pixel_frame](pixel_frame/) | Packed monochrome `Frame` plus declarative `Text` layout for pixel displays. No hardware dependency. |
| [qmc5883p](qmc5883p/) | Driver for the QST QMC5883P 3-axis magnetometer. |
| [radar](radar/) | UART drivers for the HLK-LD2450 and HLK-LD2420 presence radars, selected by model or detected on the wire. |
| [smoothing](smoothing/) | Sliding-window smoothing functions (SMA, WMA, EMA, median) for noisy sensor streams. No hardware dependency. |
| [tz_offset](tz_offset/) | Longitude-derived UTC offset plus pure-integer Gregorian calendar math. No hardware dependency. |
| [vl53l0x](vl53l0x/) | Driver for the ST VL53L0X time-of-flight distance sensor. Vendored from [github.com/uceeatz/VL53L0X](https://github.com/uceeatz/VL53L0X). |
| [vl53l5cx](vl53l5cx/) | Driver for the ST VL53L5CX 8×8 multizone time-of-flight sensor. Vendored from [mp-extras/vl53l5cx](https://github.com/mp-extras/vl53l5cx). |


## Notes
- Pylance (optional) resolves `import <pkg>` via `python.analysis.extraPaths`
in [.vscode/settings.json](../.vscode/settings.json) pointing at each package directory.
- Supporting a new MCU requires adding a new backend to all relevant packages.
- Host CPython tooling lives under [`cpython-packages/`](../cpython-packages/).
- The projects that freeze these packages onto devices live under [`../projects/`](../projects/README.md).
- Chip-specific behaviour lives behind a backend dispatch inside the package
(`os.uname().machine` check at import time), never in a project's `main.py`.
For the established pattern see
[`boot_status_led/boot_status_led/status.py`](boot_status_led/boot_status_led/status.py).
- Buses are opened from flat pin numbers at call time, not selected at import
time: [`i2c_bus/i2c_bus/__init__.py`](i2c_bus/i2c_bus/__init__.py) touches
neither `os.uname()` nor a pin until a driver calls it.


## Tests
From the repo root:
```
docker compose run --rm --build pytest /firmware-packages
docker compose run --rm pytest /firmware-packages/<pkg>/tests
```
Stubs for `machine`, `neopixel`, `ujson`, `ustruct`, `utime`, and
`micropython` come from [`cpython-packages/micropython_stubs/`](../cpython-packages/micropython_stubs/) —
one shared copy across every package.

Each package's source ends up reachable inside the test container at two paths: `/work/firmware-packages/<pkg>/` (`COPY`'d at image build time and installed editable into `/work/.venv` — the path coverage instruments) and `/firmware-packages/<pkg>/` (bind-mounted read-only from the host at runtime). Pytest targets use the bind-mount path; coverage `source` entries in [pyproject.toml](../pyproject.toml) use the `/work/...` path.
