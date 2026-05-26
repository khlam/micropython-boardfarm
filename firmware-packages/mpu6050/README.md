# mpu6050

<img src="../../images/MPU6050.jpg" width="220" alt="MPU6050 sensor">

MicroPython driver for the InvenSense MPU6050 family IMU (MPU6050,
MPU6500, MPU9250).
All MCUs read acceleration (`ax`, `ay`, `az`), gyroscope (`gx`, `gy`, `gz`), and
temperature (`temp_c`) through this shared driver.
Detects the MPU board via WHO_AM_I and applies the corresponding
temperature transfer function. Accel + gyro registers are shared.

## Layout
```
mpu6050/
  mpu6050/
    __init__.py     re-exports MPU6050
    mpu6050.py      the driver
  tests/            host pytest against a register-level simulator
```

## Public API
```python
from machine import Pin, SoftI2C
from mpu6050 import MPU6050

i2c = SoftI2C(sda=Pin(0), scl=Pin(1))
imu = MPU6050(i2c, addr=0x68)          # or 0x69 if AD0 is tied to 3V3
ax, ay, az, gx, gy, gz, temp_c = imu.read_all()
if imu.last_saturated:                 # True if any axis pegged at the int16 rail
    ...
imu.kind  # "MPU6050", "MPU6500", or "MPU9250"
```

## Notes
Units: accel in *g*, gyro in *°/s*, temp in *°C*. Ranges are fixed at
±2 g and ±250 °/s with a 44 Hz DLPF (125 Hz internal sample rate).

## Tests
From the repo root:
```
docker compose run --rm --build test -- /firmware-packages/mpu6050/tests
```
A register-level fake (`tests/fake_mpu6050.py`) drives the driver via
the stubbed I²C bus. Coverage is logic-only: WHO_AM_I dispatch, LSB
conversions, chip-specific temperature transfer, saturation flag, and
unknown-WHO_AM_I rejection. Real-chip quirks (NACK retries, clock
stretching) require hardware.

## References
- [tuupola/micropython-mpu9250](https://github.com/tuupola/micropython-mpu9250)
- [micropython-IMU/micropython-mpu9x50](https://github.com/micropython-IMU/micropython-mpu9x50)
