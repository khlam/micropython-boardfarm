# radar

UART drivers for the supported presence radars, and the vocabulary for choosing
between them. Every driver is a submodule subclassing the shared
[`ReportStream`](radar/stream.py) reader and decoding into the same `Target`
shape, so a caller reads any supported radar the same way.

| Submodule | Radar | Notes |
|---|---|---|
| [`radar/ld2450.py`](radar/ld2450.py) | HLK-LD2450 | Three tracked targets with bearing and speed. Read-only. |
| [`radar/ld2420.py`](radar/ld2420.py) | HLK-LD2420 | Presence and range only. **Writes** to the radar at startup. |
| [`radar/stream.py`](radar/stream.py) | — | The framing, wakeup, and report-selection machinery every driver shares. |

## Choose a radar

MicroPython has no `enum` module, so the model vocabulary is a class of string
constants. Each value is also the name firmware publishes in its JSON reports.

```python
import asyncio

import radar


async def main():
    device = radar.driver(radar.Model.LD2450, bus_id=0, tx=0, rx=1)
    try:
        await device.wait_ready()
        while True:
            targets = await device.read_latest()
            if targets is not None:
                print(targets)
    finally:
        device.close()


asyncio.run(main())
```

`bus_id` selects a UART on the microcontroller. `tx` and `rx` are GPIO pin
numbers. Connect the microcontroller TX pin to the radar RX pin and the
microcontroller RX pin to the radar transmit pin (`TX` on the LD2450, `OT1` on
the LD2420).

`DRIVERS` is the registry behind `driver()` — an ordered tuple of
`(model, class)` pairs rather than a dict, because MicroPython dicts are not
insertion-ordered and `detect()` depends on the order.

## Detect whichever radar is wired

When both radars share one UART and one pair of pins, `detect()` probes them in
`DRIVERS` order and returns the first that answered, releasing every probe that
stayed silent:

```python
model, device = await radar.detect(bus_id=0, tx=0, rx=1)
```

The LD2450 is probed first because its driver only reads, so an attached LD2450
is never written to. `detect()` raises `NoRadarError` when none answered, and
lets `OSError` through when the UART itself failed — a project's retry loop
tells "nothing is wired here" from "the bus is broken" that way.

## Targets

Every driver decodes into one shape, so a caller never branches on the model:

- `slot`: The radar slot number, from 1 to 3.
- `x_mm`: Side-to-side position in millimetres.
- `y_mm`: Forward position in millimetres.
- `speed_cm_s`: Speed in centimetres per second.
- `resolution_mm`: Size of one radar distance step, in millimetres.

A radar that does not measure a field reports it as zero — that is "not
measured", not a measurement. The LD2420 measures range only, so it fills
`y_mm` and leaves `x_mm`, `speed_cm_s`, and `resolution_mm` at zero.

`read_latest()` returns the targets, `()` when the newest report saw nobody, or
`None` when no complete report arrived within 500 ms.

## The shared reader

`ReportStream` opens the UART, registers an RX-idle interrupt, and exposes the
lifecycle every driver shares:

| Member | What it does |
|---|---|
| `wait_ready()` | Runs `_prepare()`, then waits up to 2 s for a first valid report. Raises `DeviceNotFoundError` if none arrives, closing the UART on every raising path. |
| `read_latest()` | Drains the UART and decodes only the newest complete report. |
| `close()` | Idempotent; disables wakeups and deinitializes the UART. |
| `_prepare()` | Optional override for a radar that must be commanded into a mode before it streams. Writes go to `self._uart`. |
| `_decode(report)` | Required override; receives one framed, validated report. |

A subclass declares its framing as seven class attributes (`NAME`, `BAUDRATE`,
`HEADER`, `FOOTER`, `REPORT_LEN`, `STARTUP_TIMEOUT_MS`, `REPORT_TIMEOUT_MS`).
Only one coroutine may read a stream at a time; a second concurrent call raises
`RuntimeError`, because the interrupt flag has one waiter. Older complete
reports are validated but never decoded, so a slow caller pays for one decode
rather than for the backlog. A UART failure raises `OSError`.

### Resynchronization
Bytes are matched one at a time. A candidate whose footer does not match is not
thrown away: an embedded header keeps its remainder, and a trailing partial
header is retained as a prefix, so a stream that starts mid-report locks on
without waiting for the radar to pause.

## Per-radar notes

**LD2450** — 256000 baud, ten 30-byte reports per second, each starting with
`AA FF 03 00` and ending with `55 CC` and carrying three target slots. The
driver never changes tracking mode, baud rate, Bluetooth, detection zones, or
other saved settings. Supply 5 V at more than 200 mA. See the
[Hi-Link LD2450 serial protocol V1.03](https://h.hlktech.com/download/HLK-LD2450-24G/1/LD2450%20%E4%B8%B2%E5%8F%A3%E9%80%9A%E4%BF%A1%E5%8D%8F%E8%AE%AE%20V1.03.pdf).

**LD2420** — 115200 baud, 45-byte energy-mode reports starting with `F4 F3 F2 F1`
and ending with `F8 F7 F6 F5`, carrying a presence byte, a two-byte distance in
centimetres, and sixteen range-gate energies that are validated but not decoded.
Unlike the LD2450 driver, this one **writes**: during `wait_ready()` it commands
system mode `0x0004`, the energy mode, so the report format does not depend on
the mode the module was last left in. That write changes a saved radar setting
and is what makes detection deterministic. Command frames start with
`FD FC FB FA` and end with `04 03 02 01`; an acknowledgement echoes the command
word with bit 8 set and follows it with a status word, where zero means success.
A malformed acknowledgement expires the 500 ms command timeout rather than being
skipped, because a device that answers a command that way is not the radar this
driver speaks to. Supply 3V3, not 5 V. See the
[HLK-LD2420 command protocol](https://github.com/soubhik-khan/HLK-LD2420) and
the [ESPHome `ld2420` component](https://github.com/esphome/esphome/tree/dev/esphome/components/ld2420).

## Pin numbers live in the project
Pin numbers are not in this package. Each project defines its own `BOARD` table
of plain pin numbers in `main.py` via `os.uname().machine` dispatch and passes
them as flat keyword arguments.

The RP2 and ESP32 ports in the project's pinned MicroPython version support
`UART.IRQ_RXIDLE`. On ESP32 this interrupt uses `Timer(0)`, so applications
using these drivers must leave that timer available. The IRQ is a wake signal
only; UART reads and report decoding run in the asyncio task. Use a common
ground.

## Tests
```
docker compose run --rm --build pytest /firmware-packages/radar/tests
```
