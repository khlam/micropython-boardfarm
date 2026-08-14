# ld2450

MicroPython driver for the HLK-LD2450 radar's read-only target stream. The
driver accepts flat UART pin numbers, opens its own UART at the factory
256000-baud setting, and recovers fixed-length reports from fragmented or noisy
input.

## Public API

```python
from ld2450 import LD2450, DeviceNotFoundError

radar = LD2450(bus_id=0, tx=0, rx=1)
targets = radar.read()
```

`LD2450(...)` waits up to `probe_ms` for a valid report and raises
`DeviceNotFoundError` if none arrives. The first valid report is cached for the
first `read()` call.

`read()` waits up to `frame_timeout_ms` and returns:

- A tuple of active `Target(slot, x_mm, y_mm, speed_cm_s, resolution_mm)`
  records, preserving report slots 1–3.
- An empty tuple when a valid report contains no targets.
- `None` when no complete valid report arrives before the timeout.

The parser validates the `AA FF 03 00` header and `55 CC` trailer, accepts
fragmented and coalesced UART reads, discards corrupt input, and bounds its
receive buffer. UART I/O failures propagate as `OSError`.

The package does not send commands or modify tracking mode, baud rate,
Bluetooth, factory settings, or detection zones. Protocol reference:
[Hi-Link LD2450 serial protocol V1.03](https://h.hlktech.com/download/HLK-LD2450-24G/1/LD2450%20%E4%B8%B2%E5%8F%A3%E9%80%9A%E4%BF%A1%E5%8D%8F%E8%AE%AE%20V1.03.pdf).

## Wiring ownership

Board pins remain project-specific. Connect MCU TX to radar RX and MCU RX to
radar TX; the radar UART uses 3.3 V logic. Supply the radar from 5 V with more
than 200 mA available and connect a common ground.

## Tests

Automated driver tests will be added after the feature behavior is confirmed,
as required by the repository testing policy.
