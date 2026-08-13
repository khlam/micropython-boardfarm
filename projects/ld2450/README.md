# LD2450

Project scaffold for an HLK-LD2450 radar sensor application.

## Status

The project structure is reserved, but the application firmware, stream schema,
dashboard, and tests are not defined yet.

## Wiring

The RP2040 target for this project is the Waveshare RP2040-Zero. Use UART0 on
GP0/GP1 so the board can both receive position reports and send configuration
commands. The UART lines cross: each device's TX connects to the other device's
RX.

```text
                 Waveshare RP2040-Zero                 HLK-LD2450
              (USB-C connector at top)             (labelled interface)

                    ┌───────────┐                    ┌───────────┐
                    │           │                    │           │
 USB 5 V rail   5V ─┤           ├───────────────────►│ 5V        │
 Common ground GND ─┤           ├───────────────────►│ GND       │
 UART0 TX       GP0 ┤           ├───────────────────►│ RX        │ config
 UART0 RX       GP1 ┤           ├◄───────────────────│ TX        │ position + ACK
                    │           │                    │           │
                    └───────────┘                    └───────────┘
```

| RP2040-Zero pin | UART role | LD2450 pin | Purpose |
| --- | --- | --- | --- |
| `5V` | — | `5V` | Powers the radar from the board's USB 5 V rail |
| `GND` | — | `GND` | Common power and signal ground |
| `GP0` | UART0 TX | `RX` | Sends configuration commands to the radar |
| `GP1` | UART0 RX | `TX` | Receives target positions and command acknowledgements |

```text
                                   ┌─── USB-C ───┐
                              ┌────┴─────────────┴────┐
                              │                       │
           LD2450 5V ◄──  5V ─┤                       ├─ 0  ────► LD2450 RX
          LD2450 GND ◄── GND ─┤                       ├─ 1  ◄──── LD2450 TX
                         3V3 ─┤                       ├─ 2
                          29 ─┤                       ├─ 3
                          28 ─┤                       ├─ 4
                          27 ─┤  [BOOT] (●) [RESET]   ├─ 5
                          26 ─┤        WS2812         ├─ 6
                          15 ─┤        on GP16        ├─ 7
                          14 ─┤                       ├─ 8
                              │  WAVESHARE RP2040-ZERO│
                              │                       │
                              └─┬────┬────┬────┬────┬─┘
                                │    │    │    │    │
                                13   12   11   10   9
```

The LD2450 requires a 5 V supply capable of more than 200 mA. Its UART uses
3.3 V TTL levels, so GP0 and GP1 connect directly without a level shifter. Do
not power the radar from the RP2040-Zero's `3V3` pin. If a separate regulated
5 V supply powers the radar, keep its ground connected to RP2040-Zero `GND`.

Use either the LD2450's socket or its pin interface, not both. Connect the four
signals by their printed labels because carrier-board connector layouts can
differ. The factory UART setting is 256000 baud, 8 data bits, no parity, and
1 stop bit. The radar transmits target data at 10 frames per second; the frames
contain X position, Y position, speed, and distance resolution for as many as
three targets. Both UART directions must remain wired because configuration
commands sent on GP0 are acknowledged on GP1.

Sources: [Hi-Link LD2450 serial protocol V1.03](https://h.hlktech.com/download/HLK-LD2450-24G/1/LD2450%20%E4%B8%B2%E5%8F%A3%E9%80%9A%E4%BF%A1%E5%8D%8F%E8%AE%AE%20V1.03.pdf),
[Hi-Link LD2450 product page](https://www.hlktech.com/Goods-226.html), and
[Waveshare RP2040-Zero documentation](https://www.waveshare.com/wiki/RP2040-Zero).

## Planned layout

```text
ld2450/
  firmware/                project-specific MicroPython application
  viz/static/              project-specific dashboard
  tests/                   host tests added after the feature is confirmed
  docker-compose.yaml      compile, flash, and dashboard services
  pyproject.toml           project metadata
```

The reusable sensor driver belongs in
[`../../firmware-packages/ld2450/`](../../firmware-packages/ld2450/). Pin
assignments and application behavior belong in this project.
