# HLK-LD2450 radar driver

This MicroPython driver reads targets from an HLK-LD2450 radar sensor. The
radar sends ten reports per second over a UART serial connection. Each report
is 30 bytes long and contains three target slots. A receive-idle interrupt
wakes one asyncio reader, which returns only the slots containing a detected
target from the newest valid report.

The driver uses the radar's factory serial setting of 256000 baud. It can join
a report that arrives in several pieces, separate several reports that arrive
together, and recover after invalid bytes. Its 512-byte UART receive buffer
holds about 1.7 seconds of the documented report stream. It reads data only
and does not change any radar settings.

## Read targets

```python
import asyncio

from ld2450 import LD2450, DeviceNotFoundError


async def main():
    radar = LD2450(bus_id=0, tx=0, rx=1)
    try:
        await radar.wait_ready()
        while True:
            targets = await radar.read_latest()
            if targets is not None:
                print(targets)
    finally:
        radar.close()


asyncio.run(main())
```

`bus_id` selects a UART on the microcontroller. `tx` and `rx` are GPIO pin
numbers. Connect the microcontroller TX pin to the radar RX pin and the
microcontroller RX pin to the radar TX pin.

Creating `LD2450` opens the UART and enables receive-idle interrupts. Call
`await wait_ready()` before reading; it waits up to two seconds for the first
valid report and raises `DeviceNotFoundError` if none arrives. Then
`await read_latest()` returns:

- A tuple containing one to three `Target` values when targets are detected.
- An empty tuple when the report contains no targets.
- `None` when no complete report arrives within 500 ms.

Each target contains:

- `slot`: The radar slot number, from 1 to 3.
- `x_mm`: Side-to-side position in millimetres.
- `y_mm`: Forward position in millimetres.
- `speed_cm_s`: Speed in centimetres per second.
- `resolution_mm`: Size of one radar distance step, in millimetres.

If several reports are waiting, the driver validates them all but decodes only
the newest one. This keeps a live display current without allocating target
objects for reports that will be discarded. Only one coroutine may call
`wait_ready()` or `read_latest()` at a time. A concurrent reader raises
`RuntimeError` because the interrupt flag has one waiter.

Each report starts with `AA FF 03 00` and ends with `55 CC`. The driver uses
these markers to reject invalid data. A UART read failure raises `OSError`.
Call `close()` to disable the interrupt and deinitialize the UART; repeated
calls are harmless. The driver never changes tracking mode, baud rate,
Bluetooth, detection zones, or other saved radar settings. See the
[Hi-Link LD2450 serial protocol V1.03](https://h.hlktech.com/download/HLK-LD2450-24G/1/LD2450%20%E4%B8%B2%E5%8F%A3%E9%80%9A%E4%BF%A1%E5%8D%8F%E8%AE%AE%20V1.03.pdf).

The RP2 and ESP32 ports in the project's pinned MicroPython version support
`UART.IRQ_RXIDLE`. On ESP32 this interrupt uses `Timer(0)`, so applications
using this driver must leave that timer available. The IRQ is a wake signal
only; UART reads and report decoding run in the asyncio task.

Use a common ground and supply the radar with 5 V at more than 200 mA. Each
project chooses its own UART and GPIO pins.
