# HLK-LD2420 radar driver

This MicroPython driver reads presence and range from an HLK-LD2420 radar
sensor. The radar measures range only: one presence flag and one distance, with
no bearing and no speed. A receive-idle interrupt wakes one asyncio reader,
which returns the detected target from the newest valid report.

The driver uses the radar's factory serial setting of 115200 baud. It can join a
report that arrives in several pieces, separate several reports that arrive
together, and recover after invalid bytes.

Unlike the [ld2450](../ld2450/) driver, this one **writes** to the radar. During
`wait_ready()` it commands system mode `0x0004`, the energy mode, so the report
format does not depend on the mode the module was last left in. That write
changes a saved radar setting and is what makes detection deterministic.

## Read presence

```python
import asyncio

from ld2420 import LD2420, DeviceNotFoundError


async def main():
    radar = LD2420(bus_id=0, tx=0, rx=1)
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
numbers. Connect the microcontroller TX pin to the radar `RX` pin and the
microcontroller RX pin to the radar `OT1` pin. The radar's `OT2` presence output
is not used.

Creating `LD2420` opens the UART and enables receive-idle interrupts. Call
`await wait_ready()` before reading; it runs the configuration sequence and then
waits up to two seconds for the first valid report. It raises
`DeviceNotFoundError` if the radar rejects a command, does not acknowledge one,
or sends no valid report. Then `await read_latest()` returns:

- A one-element tuple containing a `Target` when the radar detects presence.
- An empty tuple when the radar detects nobody.
- `None` when no complete report arrives within 500 ms.

Each target contains:

- `distance_mm`: Distance to the detected target in millimetres, converted from
  the centimetres the radar reports.

If several reports are waiting, the driver validates them all but decodes only
the newest one. Only one coroutine may call `wait_ready()` or `read_latest()` at
a time. A concurrent reader raises `RuntimeError` because the interrupt flag has
one waiter.

## Notes

Each energy-mode report is 45 bytes: it starts with `F4 F3 F2 F1`, ends with
`F8 F7 F6 F5`, and carries a presence byte, a two-byte distance in centimetres,
and one two-byte energy value for each of the sixteen range gates. The gate
energies are validated as part of the report but are not decoded. Framing and
report selection are the shared [uart_reports](../uart_reports/) reader; this
package supplies the markers, the command sequence, and the decoder.

Command frames start with `FD FC FB FA` and end with `04 03 02 01`. An
acknowledgement echoes the command word with bit 8 set and follows it with a
status word, where zero means success. A malformed acknowledgement expires the
500 ms command timeout rather than being skipped, because a device that answers
a command that way is not the radar this driver speaks to.

A UART read or write failure raises `OSError`. Call `close()` to disable the
interrupt and deinitialize the UART; repeated calls are harmless.

The RP2 and ESP32 ports in the project's pinned MicroPython version support
`UART.IRQ_RXIDLE`. On ESP32 this interrupt uses `Timer(0)`, so applications using
this driver must leave that timer available. The IRQ is a wake signal only; UART
reads and report decoding run in the asyncio task.

Use a common ground and supply the radar with 3V3, not 5 V. Each project chooses
its own UART and GPIO pins.

## Tests

```console
docker compose run --rm --build pytest /firmware-packages/ld2420/tests
```

## References

- [HLK-LD2420 command protocol](https://github.com/soubhik-khan/HLK-LD2420)
- [ESPHome `ld2420` component](https://github.com/esphome/esphome/tree/dev/esphome/components/ld2420)
