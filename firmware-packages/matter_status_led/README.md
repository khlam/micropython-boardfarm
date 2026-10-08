# matter_status_led

Shows the Matter device state on one status pixel, with colour and blink, so
every Matter project tells you the same thing the same way. The project passes
in its own NeoPixel; the package claims no pin.

Colour says which state the device is in. Blink says whether it is waiting
(slow, 1 Hz), working (fast, 5 Hz), or stuck (solid).

## What the pixel shows

Highest priority first:

| Matter state | Pixel |
| --- | --- |
| A commissioning attempt just failed | Red, three quick flashes, then the row below that applies |
| Before the first poll | Dim white, solid |
| Commissioning: a controller is pairing | Cyan, fast blink |
| Uncommissioned, window open | Purple, slow blink |
| Uncommissioned, no window | Amber, solid — nobody can reach the device |
| Operational, Wi-Fi down | Amber, slow blink |
| Operational, window open for another controller | Purple, slow blink |
| Operational and connected | The application's colour, solid |

The fabric state outranks the network, which outranks an open window. See the
[matter README](../matter/README.md#key-flows) for the states themselves.

## Public API

```python
from matter_status_led import StatusLed

status = StatusLed(pixel, level=25)    # dim white until the first set_state()
status.set_state(node.state)           # after every Node.poll()
status.set_application((0, 25, 0))     # shown once Matter calls for nothing
status.fail()                          # on a StateEvent whose failed is True
status.tick()                          # from the loop, at least every 50 ms
```

`level` caps every status colour's brightest channel, so `level=25` keeps
status at ten percent of full scale. Application colours show as given. Only
`tick()` writes the pixel, and only when its colour changes.

## Layout

```
matter_status_led/
  matter_status_led/
    __init__.py   re-exports StatusLed
    pattern.py    state-to-pattern table, brightness scaling, blink timing (pure)
    led.py        StatusLed: picks the pattern and drives the pixel over time
```

See the [Matter light](../../projects/matter/README.md) and
[occupancy sensor](../../projects/matter-radar-sensor/README.md) projects for
the two callers.
