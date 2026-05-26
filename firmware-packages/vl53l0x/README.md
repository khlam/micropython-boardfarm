# vl53l0x

<img src="../../images/VL53L0X.jpg" width="220" alt="VL53L0X sensor">

MicroPython driver for the ST VL53L0X time-of-flight distance sensor.
All MCUs read distance identically through this shared driver.
Vendored from [github.com/uceeatz/VL53L0X](https://github.com/uceeatz/VL53L0X).


## Layout
```
vl53l0x/
  vl53l0x/
    __init__.py     re-exports VL53L0X
    vl53l0x.py      vendored driver (excluded from ruff; see pyproject.toml)
  tests/            host pytest against a register-level simulator
```

## Public API
```python
from machine import Pin, SoftI2C
from vl53l0x import VL53L0X

i2c = SoftI2C(sda=Pin(0), scl=Pin(1))
tof = VL53L0X(i2c, skip_spad_info=True, interrupt_status_mask=0x07)
tof.start()
mm = tof.read()    # ≥ 8190 means OUT_OF_RANGE; otherwise distance in mm
```

## Notes
- `skip_spad_info` — skip the SPAD-info handshake during init. Required on
  the ESP32-S3-Zero breakout, where the read of register 0x83 NACKs;
  harmless on RP2040/RP2350.
- `interrupt_status_mask` — bits in `RESULT_INTERRUPT_STATUS` (0x13) that
  signal "measurement ready". Default `0x07` works on RP2040/RP2350; pass
  `0xFF` on ESP32-S3, where the breakout signals via bit 6 only.

## Tests
From the repo root:
```
docker compose run --rm --build test -- /firmware-packages/vl53l0x/tests
```
A register-level fake (`tests/fake_vl53l0x.py`) drives the driver via the
stubbed I²C bus. Coverage is logic-only: sequencing, retries, mask
handling, `skip_spad_info`. Real-chip quirks (NACK retries, clock-stretch
timeouts) require hardware.
