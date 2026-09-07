# vl53l0x

<img src="../../images/VL53L0X.jpg" width="220" alt="VL53L0X sensor">

MicroPython driver for the ST VL53L0X time-of-flight distance sensor.
All MCUs read distance identically through this shared driver.
Vendored from [github.com/uceeatz/VL53L0X](https://github.com/uceeatz/VL53L0X).


## Layout
```
vl53l0x/
  vl53l0x/
    __init__.py     wrapper: bus creation, device scan, soft-reset, defaults
    vl53l0x.py      vendored driver (excluded from ruff; see pyproject.toml)
  tests/            host pytest against a register-level simulator
```

## Public API
```python
from vl53l0x import VL53L0X, DeviceNotFoundError

tof = VL53L0X(sda=0, scl=1)   # opens its own soft I²C, scans, soft-resets
tof.start()
mm = tof.read()    # ≥ 8190 means OUT_OF_RANGE; otherwise distance in mm
```

Arguments are keyword-only and are plain pin numbers from the project's `BOARD`
table — the project never builds an I²C object. `DeviceNotFoundError` is
re-exported here, so a retry loop imports it from this package rather than from
`i2c_bus`.

## Notes
- `skip_spad_info` — skip the SPAD-info handshake during init. Default `True`.
  Required on the ESP32-S3-Zero breakout, where the read of register 0x83
  NACKs; harmless on RP2040/RP2350.
- `interrupt_status_mask` — bits in `RESULT_INTERRUPT_STATUS` (0x13) that
  signal "measurement ready". Default `0xFF` covers both RP2040/RP2350
  (bits 0–2) and ESP32-S3, where the breakout signals via bit 6 only.
- `address` — 7-bit I²C address; default `0x29`. Nothing ACKing there raises
  `DeviceNotFoundError`.
- The vendored `vl53l0x.py` still takes a ready-made `i2c` object with upstream
  defaults; the wrapper above is the supported entry point.

## Tests
From the repo root:
```
docker compose run --rm --build pytest /firmware-packages/vl53l0x/tests
```
A register-level fake (`tests/fake_vl53l0x.py`) drives the driver via the
stubbed I²C bus. Coverage is logic-only: sequencing, retries, mask
handling, `skip_spad_info`. Real-chip quirks (NACK retries, clock-stretch
timeouts) require hardware.
