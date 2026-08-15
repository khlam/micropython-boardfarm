# HLK-LD2450 radar driver

This MicroPython driver reads targets from an HLK-LD2450 radar sensor. The
radar sends ten reports per second over a UART serial connection. Each report
is 30 bytes long and contains three target slots. The driver returns only the
slots that contain a detected target.

The driver uses the radar's factory serial setting of 256000 baud. It can join
a report that arrives in several pieces, separate several reports that arrive
together, and skip invalid bytes. It reads data only and does not change any
radar settings.

## Read targets

```python
from ld2450 import LD2450, DeviceNotFoundError

radar = LD2450(bus_id=0, tx=0, rx=1)
targets = radar.read()
```

`bus_id` selects a UART on the microcontroller. `tx` and `rx` are GPIO pin
numbers. Connect the microcontroller TX pin to the radar RX pin and the
microcontroller RX pin to the radar TX pin.

Creating `LD2450` waits up to two seconds for the first valid report. It raises
`DeviceNotFoundError` if no valid report arrives. `read()` then waits up to 500 ms
for each report and returns:

- A tuple containing one to three `Target` values when targets are detected.
- An empty tuple when the report contains no targets.
- `None` when no complete report arrives within 500 ms.

Each target contains:

- `slot`: The radar slot number, from 1 to 3.
- `x_mm`: Side-to-side position in millimetres.
- `y_mm`: Forward position in millimetres.
- `speed_cm_s`: Speed in centimetres per second.
- `resolution_mm`: Size of one radar distance step, in millimetres.

Use `read_latest()` for a live display. If several reports are waiting, it
skips the older reports and returns the newest target positions. Its return
values are otherwise the same as `read()`.

Each report starts with `AA FF 03 00` and ends with `55 CC`. The driver uses
these markers to reject invalid data. A UART read failure raises `OSError`.
The driver never changes tracking mode, baud rate, Bluetooth, detection zones,
or other saved radar settings. See the
[Hi-Link LD2450 serial protocol V1.03](https://h.hlktech.com/download/HLK-LD2450-24G/1/LD2450%20%E4%B8%B2%E5%8F%A3%E9%80%9A%E4%BF%A1%E5%8D%8F%E8%AE%AE%20V1.03.pdf).

Use a common ground and supply the radar with 5 V at more than 200 mA. Each
project chooses its own UART and GPIO pins.
