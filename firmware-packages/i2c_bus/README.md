# i2c_bus

Internal I²C bus helpers, consumed only by sensor drivers. A driver supplies
plain pin numbers from the project's `BOARD` table and gets back a ready
`machine.I2C` / `SoftI2C`; the project never sees this package.

## Public API
```python
from i2c_bus import DeviceNotFoundError, hard_i2c, soft_i2c

bus = hard_i2c(bus_id=0, sda=0, scl=1)   # sensors that don't clock-stretch (MPU6050)
bus = soft_i2c(sda=0, scl=1)             # sensors that do (VL53L0X / VL53L5CX)
```

`soft_i2c` defaults to 100 kHz, `hard_i2c` to 400 kHz; pass `freq=` to override.
`soft_i2c` is bit-banged and has no `bus_id`.

## Pin numbers live in the project
Pin numbers are not in this package. Each project defines its own `BOARD` table
of plain pin numbers in `main.py` via `os.uname().machine` dispatch and passes
them as flat keyword arguments to the driver, which forwards them here.

## Tests
```
docker compose up pytest --build --exit-code-from pytest -- /firmware-packages/i2c_bus/tests
```
