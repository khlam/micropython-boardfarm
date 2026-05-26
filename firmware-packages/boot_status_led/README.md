# boot_status_led

Boot/runtime LED state machine. 
Enables all project MCUs to share the same `status` LED states:
`boot`, `i2c_init`, `no_device`, `init_err`, `streaming`, `read_err`.

## Layout
```
boot_status_led/
  boot_status_led/
    __init__.py     re-exports `status`
    status.py       named transitions + colour constants, chip dispatch
    rp2040.py       WS2812 on GP16 (RP2040-Zero)
    rp2350.py       CYW43 user LED, on/off only (Pico 2 W)
    esp32s3.py      WS2812 on GPIO21 (ESP32-S3-Zero)
  tests/            host pytest (CPython + stubbed machine/neopixel)
```

## Public API
```python
from boot_status_led import status

status.boot()       # white   — firmware running, before any I/O
status.i2c_init()   # cyan    — I²C bus configured, scanning for device(s)
status.no_device()  # orange  — bus reachable, device(s) not present
status.init_err()   # magenta — device(s) ACKed but driver init raised
status.streaming()  # green   — device(s) live, samples flowing
status.read_err()   # red     — transient I²C fault during streaming
```

## Notes

### Boot LED states

RP2040-Zero and ESP32-S3-Zero use a full-colour WS2812. The RP2350 uses a green LED and is on/off only.

| State       | RP2040-Zero & ESP32-S3-Zero | RP2350 |
|------|-----------------------------|--------|
| Boot        | White                       | Off    |
| I²C init    | Cyan                        | Off    |
| No device   | Orange                      | Off    |
| Init error  | Magenta                     | Off    |
| Streaming   | Green                       | On     |
| Read error  | Red flash (200 ms)          | Brief off (200 ms) |

## Tests
From the repo root:
```
docker compose run --rm --build pytest /firmware-packages/boot_status_led/tests
```