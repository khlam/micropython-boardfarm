# vl53l5cx

MicroPython driver for the VL53L5CX 8×8 multizone time-of-flight sensor.
Vendored and adapted from [mp-extras/vl53l5cx](https://github.com/mp-extras/vl53l5cx) (MIT).
See [VENDOR.md](VENDOR.md) for the source commit and divergence notes.

## Public API

```python
from vl53l5cx import VL53L5CX

tof = VL53L5CX(i2c, address=0x29, lpn=None)
tof.init()           # load ~86.5 KB ST firmware over I²C (~7-9 s at 100 kHz soft I²C, ~2-3 s at 400 kHz)
tof.start(freq=10)   # set 8×8 resolution, freq Hz, begin ranging
while True:
    if tof.check_data_ready():
        grid = tof.read()   # list of 64 int|None, row-major
tof.stop()
```

`read()` returns a flat list of 64 elements (row 0 first). Each element is an
integer distance in mm, or `None` when `target_status` is not `STATUS_VALID`
(5) or `STATUS_VALID_LARGE_PULSE` (9).

Advanced use exposes the full upstream API: `start_ranging(enables)`,
`get_ranging_data()`, `stop_ranging()`, and properties `resolution`,
`ranging_freq`, `integration_time_ms`, `target_order`, `ranging_mode`,
`power_mode`, `sharpener_percent`.

## Layout

```
firmware-packages/vl53l5cx/
├── vl53l5cx/
│   ├── __init__.py       # exports VL53L5CX
│   ├── vl53l5cx.py       # vendored driver (do not edit; see VENDOR.md)
│   └── _config_bytes.py  # vendored firmware binary as bytes (do not edit)
├── tests/
│   ├── conftest.py
│   └── test_vl53l5cx.py
├── pyproject.toml
├── VENDOR.md
└── README.md
```

Only the inner `vl53l5cx/` directory is frozen onto the MCU; `tests/`,
`pyproject.toml`, and `README.md` stay on the host.

## Running tests

```bash
# from repo root
docker compose run --rm pytest /firmware-packages/vl53l5cx/tests
```
