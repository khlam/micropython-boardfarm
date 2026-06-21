# i2c_bus

MCU package that builds an I²C bus from a `Wiring` record supplied by the caller.
The package owns *what* pins it needs (the `Wiring` schema); the project's `BOARD`
table owns *which* pins, dispatched per chip.

## Public API
```python
from i2c_bus import Wiring, soft_i2c, hard_i2c

Wiring  # namedtuple("Wiring", ("id", "sda", "scl")) — id selects the hard-I²C peripheral

bus = hard_i2c(Wiring(id=0, sda=0, scl=1))   # sensors that don't clock-stretch (MPU6050)
bus = soft_i2c(Wiring(id=0, sda=0, scl=1))   # sensors that do (VL53L0X / VL53L5CX)
```

`soft_i2c` defaults to 100 kHz, `hard_i2c` to 400 kHz; pass `freq=` to override.
`soft_i2c` is bit-banged and ignores `wiring.id`.

## Wiring lives in the project
Pin numbers are not in this package. Each project fills `Wiring` per chip in its
`main.py` `BOARD` table via `os.uname().machine` dispatch and passes it to the factory.

## Tests
```
docker compose up pytest --build --exit-code-from pytest -- /firmware-packages/i2c_bus/tests
```
