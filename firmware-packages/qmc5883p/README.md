# qmc5883p

<img src="../../images/qmc5883p.jpg" width="220" alt="QMC5883P GY-271 breakout">

MicroPython driver for the QST **QMC5883P** 3-axis magnetometer.

Despite the near-identical name, the QMC5883P is a *different* chip from the
QMC5883L — different register map, a fixed I²C address of `0x2C`, and an
axis-sign quirk. All MCUs read raw magnetic field counts (`x`, `y`, `z`) through
this shared, chip-agnostic driver.

## Layout
```
qmc5883p/
  qmc5883p/
    __init__.py     re-exports QMC5883P
    qmc5883p.py     the driver
  tests/            host pytest against a register-level simulator
```

## Public API
```python
from machine import Pin, I2C
from qmc5883p import QMC5883P

i2c = I2C(0, sda=Pin(0), scl=Pin(1), freq=400_000)
mag = QMC5883P(i2c)            # fixed I²C address 0x2C; raises OSError on chip-ID mismatch
x, y, z = mag.read()          # blocks until data-ready; signed LSB counts
if mag.last_status & 0x02:    # OVL bit — field saturation (magnet too close)
    ...
```

Heading is application-level and intentionally left to the caller:
`heading = (degrees(atan2(y, x)) + 360) % 360`.

## Notes
- Fixed I²C address `0x2C` (not configurable).
- `__init__` verifies the chip-ID register (`0x00` → `0x80`) and raises `OSError`
  on mismatch, then soft-resets, inverts X/Y (`AXIS_SIGN` = `0x06`) so the frame
  matches the QMC5883L convention, selects ±2 G range, and starts continuous
  output at 50 Hz with OSR=512 (maximum in-sensor averaging).
- `read()` blocks on the STATUS data-ready bit (~20 ms at 50 Hz) and returns
  `(x, y, z)` signed ints — self-paced, so the caller's loop needs no sleep.
- The driver imports `utime` (not `time`) so the data-ready poll's `sleep_ms`
  resolves both on-device and under the host-test stub.

## Tests
From the repo root:
```
docker compose run --rm --build pytest /firmware-packages/qmc5883p/tests
```
A register-level fake (`tests/fake_qmc5883p.py`) drives the driver via the
stubbed I²C bus. Coverage is logic-only: chip-ID validation, the init register
sequence, signed little-endian decode, the data-ready poll loop, and the OVL
status bit. Real-chip quirks (NACK retries, clock stretching) require hardware.

## References
- [adafruit/Adafruit_QMC5883P](https://github.com/adafruit/Adafruit_QMC5883P)
- [robert-hh/QMC5883](https://github.com/robert-hh/QMC5883)
