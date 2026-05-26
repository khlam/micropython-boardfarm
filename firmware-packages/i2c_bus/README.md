# i2c_bus

MCU package exposing `soft_i2c` and `hard_i2c` bus objects.

## Layout
```
i2c_bus/
  i2c_bus/
    __init__.py     dispatches to a backend based on os.uname().machine
    rp2040.py       GP0=SDA, GP1=SCL — exposes soft_i2c + hard_i2c
    rp2350.py       GP0=SDA, GP1=SCL — same wiring as RP2040
    esp32s3.py      GPIO1=SDA, GPIO2=SCL — exposes soft_i2c + hard_i2c
```

## Public API
```python
from i2c_bus import soft_i2c   # for sensors that clock-stretch (e.g. VL53L0X)
from i2c_bus import hard_i2c   # sensors that don't (e.g. MPU6050)
```

## Notes
None

**Adding a new chip:**
1. Add a backend module under `i2c_bus/` named `<chip>.py` exposing
   both `soft_i2c` and `hard_i2c`.
2. Extend the dispatch in `i2c_bus/__init__.py` with a new
   `os.uname().machine` substring match.
3. Update `boot_status_led` similarly so the LED has a backend too.

## Tests
None, this package is a pin-wiring layer.
