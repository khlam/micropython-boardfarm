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
| [boot_status_led](boot_status_led/) | Boot/runtime indicator LED state machine. |
| [i2c_bus](i2c_bus/) | Import-time–selected `SoftI2C` / `I2C` instance per chip |
| [pixel_frame](pixel_frame/) | Frame construction, packed drawing, and text rendering for pixel displays. |
| [pixel_display](pixel_display/) | Hardware-agnostic `Display` facade for pixel backends. |
| [mpu6050](mpu6050/) | Driver for the InvenSense MPU family IMU (MPU6050 / MPU6500 / MPU9250)|
| [qmc5883p](qmc5883p/) | Driver for the QST QMC5883P 3-axis magnetometer. |
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
For the established pattern see,
  - [`boot_status_led/boot_status_led/status.py`](boot_status_led/boot_status_led/status.py)
  - [`i2c_bus/i2c_bus/__init__.py`](i2c_bus/i2c_bus/__init__.py)


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
