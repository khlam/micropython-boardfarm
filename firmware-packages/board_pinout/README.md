# board_pinout

The **single source of truth** for each board's wiring. Projects own their
wiring: `main.py` reads `BOARD` and passes pins explicitly into each package's
`connect()`. Packages no longer claim pins at import time.

## Layout
```
board_pinout/
  board_pinout/
    __init__.py      namedtuple types + os.uname() dispatch + RP2040_ZERO_BANNED
    rp2040_zero.py   BOARD instance — RP2040-Zero
    rp2350.py        BOARD instance — RP2350
    esp32s3_zero.py  BOARD instance — ESP32-S3-Zero
```

## Public API
```python
from board_pinout import BOARD

BOARD.spi          # SpiBus(id, sck, mosi, miso)   — shared SPI lines
BOARD.i2c          # I2cBus(id, sda, scl)          — shared I2C lines
BOARD.uart         # UartBus(id, tx, rx)           — shared UART lines
BOARD.devices      # {name: Device(bus, cs, addr)} — per-device attachments
BOARD.status_led   # on-board LED (documented only; owned by boot_status_led)
```

A bus carries only the lines it **shares**. A device names which bus it hangs
off plus its **device-specific** line — `cs` for SPI, `addr` for I2C (`None`
when N/A). `connect()` receives one device's resolved pins, e.g.:

```python
from board_pinout import BOARD
from max7219 import connect as display_connect

display = display_connect(
    spi_id=BOARD.spi.id, sck=BOARD.spi.sck, mosi=BOARD.spi.mosi,
    cs=BOARD.devices["display"].cs,   # CS is the device's, SCK/MOSI are the bus's
)
```

## Pin tables

These tables are authoritative. `tests/test_board_pinout.py` asserts the `BOARD`
instances match them, that no GPIO is double-booked within a board, and (for the
RP2040-Zero) that no signal pin lands on an underside pad.

### RP2040-Zero
| Bus / device | id | Pins |
| --- | --- | --- |
| I²C (`i2c`) | I2C0 | SDA=GP0, SCL=GP1 |
| UART (`uart`) | UART1 | TX=GP4, RX=GP5 |
| SPI (`spi`) | SPI1 | SCK=GP10, MOSI=GP11, MISO=— |
| `devices["display"]` (MAX7219) | on `spi` | CS=GP9 |
| `devices["gps"]` (ATGM336H) | on `uart` | — |
| status LED (on-board) | — | GP16 WS2812 |

### RP2350
Mirrors the RP2040-Zero edge wiring (I2C0 GP0/GP1, UART1 GP4/GP5, SPI1
GP10/GP11 + CS GP9). `status_led="LED"` (CYW43 digital, not a GPIO number).

### ESP32-S3-Zero
| Bus / device | id | Pins |
| --- | --- | --- |
| I²C (`i2c`) | I2C0 | SDA=GPIO1, SCL=GPIO2 |
| UART (`uart`) | UART1 | TX=GPIO17, RX=GPIO18 |
| SPI (`spi`) | SPI1 | SCK=GPIO12, MOSI=GPIO11, MISO=— |
| `devices["display"]` (MAX7219) | on `spi` | CS=GPIO10 |
| `devices["gps"]` (ATGM336H) | on `uart` | — |
| status LED (on-board) | — | GPIO21 WS2812 |

## Pin ban (RP2040-Zero underside pads)

GP17/GP18/GP19 on the RP2040-Zero are **underside solder pads**, not edge
castellations — banned from signal use. The ban is the constant
`RP2040_ZERO_BANNED = (17, 18, 19)` in `__init__.py` and is enforced by
`test_rp2040_zero_avoids_underside_pads`. The **only** sanctioned override is to
remove a pin from that tuple with an explicit inline justification. (GP16 drives
the on-board WS2812 and is likewise unavailable for external wiring.)

## Multi-device & control-loop agnosticism

The structure is **declarative pin topology only** — it encodes no read order,
timing, or concurrency. That keeps it agnostic to a project's control loop
(cooperative single loop, `_thread`, IRQ callbacks, …).

- **Several devices per bus is first-class.** SPI devices are CS-muxed (shared
  `sck`/`mosi`, distinct `Device.cs`); I²C devices are address-muxed (shared
  `sda`/`scl`, distinct `Device.addr`, discovered via `i2c.scan()`). Adding a
  device is one more `Device` entry — the bus descriptor is unchanged. UART is
  point-to-point: a second UART device means a second `UartBus` id.
- **Cross-bus parallel reads are enabled by construction.** UART/SPI/I²C sit on
  disjoint pins (enforced by `test_no_duplicate_physical_pins`), so a project may
  pump them concurrently with zero contention.
- **Same-bus reads are serialized by the silicon**, not by this layer — it
  exposes the shared bus + per-device CS/addr and leaves scheduling to the
  project.

## Adding a new board
1. Add a backend module under `board_pinout/` exposing a `BOARD = Board(...)`.
2. Extend the dispatch in `__init__.py` with a new `os.uname().machine` match.
3. Add its pin table above and a case to `tests/test_board_pinout.py`.

## Tests
`tests/test_board_pinout.py` — dispatch, pin uniqueness, device integrity, and
the RP2040-Zero edge/underside guards.
