# ld2450

Read-only MicroPython driver for the HLK-LD2450 target stream. It opens its own
UART at the factory 256000-baud setting and recovers fixed-length reports from
fragmented, coalesced, corrupt, or noisy input.

```python
from ld2450 import LD2450, DeviceNotFoundError

radar = LD2450(bus_id=0, tx=0, rx=1)
targets = radar.read()
```

`LD2450(...)` accepts flat UART pin numbers, waits up to `probe_ms` for a valid
report, raises `DeviceNotFoundError` if none arrives, and caches the first valid
report. `read()` waits up to `frame_timeout_ms` and returns:

- A tuple of active `Target(slot, x_mm, y_mm, speed_cm_s, resolution_mm)`
  records, preserving slots 1–3.
- An empty tuple for a valid report with no targets.
- `None` when no complete report arrives before the timeout.

The parser validates the `AA FF 03 00` header and `55 CC` trailer and propagates
UART failures as `OSError`. It never changes tracking mode, baud rate,
Bluetooth, detection zones, or other persistent configuration. See the
[Hi-Link LD2450 serial protocol V1.03](https://h.hlktech.com/download/HLK-LD2450-24G/1/LD2450%20%E4%B8%B2%E5%8F%A3%E9%80%9A%E4%BF%A1%E5%8D%8F%E8%AE%AE%20V1.03.pdf).

Board pins remain project-owned. Cross MCU TX to radar RX and MCU RX to radar
TX, use a common ground, and supply the radar with 5 V at more than 200 mA.
