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
The wrapper takes flat pin numbers and opens its own soft-I²C bus internally:
```python
from vl53l0x import VL53L0X

tof = VL53L0X(sda=0, scl=1, skip_spad_info=True, interrupt_status_mask=0x07)
tof.start()
mm = tof.read()    # blocks ~1 timing budget; ≥ 8190 means OUT_OF_RANGE, else mm
```

Wire the chip's GPIO1 "new sample ready" output to `int_pin` for non-blocking,
interrupt-driven reads — read only when a sample is ready, so the caller's loop
never blocks on the sensor:
```python
tof = VL53L0X(sda=0, scl=1, int_pin=4)
tof.start()
if tof.data_ready:     # raised by the GPIO1 falling-edge ISR
    mm = tof.read()    # returns immediately; clears the flag and re-arms the edge
```

## Notes
- `skip_spad_info` — skip the SPAD-info handshake during init. Required on
  the ESP32-S3-Zero breakout, where the read of register 0x83 NACKs;
  harmless on RP2040/RP2350.
- `interrupt_status_mask` — bits in `RESULT_INTERRUPT_STATUS` (0x13) that
  signal "measurement ready". Default `0x07` works on RP2040/RP2350; pass
  `0xFF` on ESP32-S3, where the breakout signals via bit 6 only.
- `int_pin` — optional GPIO wired to the chip's GPIO1 output (which `init()`
  already configures as active-low new-sample-ready). When set, a falling-edge
  interrupt raises `data_ready`; omit it to use the blocking `read()`.
- `data_ready` — property, True once GPIO1 has flagged a fresh sample and until
  `read()` consumes it. Always False when no `int_pin` was wired.

## Tests
From the repo root:
```
docker compose run --rm --build test -- /firmware-packages/vl53l0x/tests
```
A register-level fake (`tests/fake_vl53l0x.py`) drives the driver via the
stubbed I²C bus. Coverage is logic-only: sequencing, retries, mask
handling, `skip_spad_info`. Real-chip quirks (NACK retries, clock-stretch
timeouts) require hardware.
