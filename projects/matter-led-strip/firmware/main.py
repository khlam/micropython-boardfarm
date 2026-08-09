"""Expose an external WS2812B strip through ESP-Matter as one Extended Color Light.

Definitions first, boot sequence at the bottom. The module runs once at boot,
then drops to the REPL with `strip`, `node`, `endpoint`, and the functions
below still in scope, so a serial session can drive the light and administer
the node.

The commissioning-status light show (boot/ready/pairing/failure colours) and
the boot-cache read/write live in `commissioning_status.py` and
`boot_cache.py`; this file owns the strip hardware and the two paths that set
a real, controller-meaningful colour: `set_color` (local/REPL) and
`on_remote_write` (a controller write).

Calls into `matter.Node`, `Node.start`, or an `Endpoint` attribute leave this
file for compiled code that drives ESP-Matter/CHIP; see
`firmware-packages/matter/ARCHITECTURE.md` for the call-path diagrams.
"""

import os
import time
from collections import namedtuple

import machine
import neopixel
from color import matter_to_triple, publish_triple

import boot_cache
import commissioning_status
import matter

# data_pin is the external strip's data line, kept separate from the onboard
# WS2812. Only ESP32-S3 is supported, so any other chip is a build error.
Board = namedtuple("Board", ("name", "data_pin"))
_machine = os.uname().machine
if "ESP32S3" not in _machine:
    raise RuntimeError(f"unsupported board: {_machine}")
BOARD = Board(name="ESP32-S3-Zero", data_pin=7)

LED_COUNT = 20

# Last colour on_remote_write actually rendered
_last_remote_color = [None]


def render(color: tuple) -> None:
    """Drive the strip. Every hardware touch in this project is these two lines."""
    for i in range(LED_COUNT):
        strip[i] = color
    strip.write()


def set_color(color: tuple) -> None:
    """Show a colour locally, then publish it to Matter.

    Colour is published before power, so a controller never briefly sees the
    old colour lit.

    Args:
        color: Red, green, and blue channel values in the range 0-255.
    """
    commissioning_status.show(color, time.ticks_ms())
    # Below: Endpoint.publish -> _matter.attribute_publish -> request.cpp
    # matter_attribute_publish -- a bounded round trip onto the CHIP task
    # (ARCHITECTURE.md "A local change going out").
    publish_triple(endpoint, color)
    lit = endpoint.level != 0
    if endpoint.on != lit:
        endpoint.on = lit
    if commissioning_status.is_commissioned():
        boot_cache.save(on=lit, color=color)


def on_remote_write(_event: object) -> None:
    """Show the colour a controller just wrote, unless it repeats the last one shown.

    The event only names the one attribute that changed, so the full colour
    is read back from the endpoint instead of computed from the event. Comparing
    against the last colour actually rendered drops a repeat before it
    reaches the bit-banged NeoPixel write.

    Args:
        _event: Unused. Only wakes this callback.
    """
    color = matter_to_triple(endpoint)
    if color == _last_remote_color[0]:
        return
    _last_remote_color[0] = color
    commissioning_status.show(color, time.ticks_ms())
    if commissioning_status.is_commissioned():
        boot_cache.save(on=endpoint.on, color=color)


strip = neopixel.NeoPixel(machine.Pin(BOARD.data_pin, machine.Pin.OUT), LED_COUNT)
commissioning_status.bind_render(render)

# A previously-commissioned board that has shown a real colour restores that
# colour immediately, before Matter's own (much slower) native restore is even
# reachable -- see commissioning_status.py's module docstring. Everything else
# still sees today's dim-white boot colour.
_startup_stamp = time.ticks_ms()
_cached = boot_cache.load()
_boot_color = tuple(_cached["color"]) if _cached is not None else commissioning_status.BOOT_COLOR
commissioning_status.show(_boot_color, _startup_stamp)

node = matter.Node()

# No initial state passed: every attribute here is one a controller owns, and
# pinning one now would overwrite what persistence is about to restore.
endpoint = node.create_endpoint(matter.EndpointType.EXTENDED_COLOR_LIGHT)
commissioning_status.bind_node(node, endpoint)

endpoint.on_write(on_remote_write)

# Queued transitions may be delivered before start() returns. The callback
# records any action that requires a started node and show_post_start_state()
# completes it below.
node.on_commissioning(commissioning_status.on_commissioning)

node.start()

# A commissioned board restores its last controller-owned colour, applied
# uniformly across the strip. An uncommissioned board settles on green unless
# a queued window/session event selected purple or cyan. fabrics() takes the
# same bounded request.cpp round trip as the attribute writes above.
commissioning_status.show_post_start_state(has_fabric=bool(node.fabrics()), startup_stamp=_startup_stamp)
