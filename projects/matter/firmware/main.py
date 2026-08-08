"""Expose the ESP32-S3-Zero onboard WS2812 through ESP-Matter.

Definitions first, boot sequence at the bottom. The module runs once at boot,
then drops to the REPL with `pixel`, `node`, `endpoint`, and the functions
below still in scope, so a serial session can drive the light and administer
the node.

Calls into `matter.Node`, `Node.start`, or an `Endpoint` attribute leave this
file for compiled code: `matter/` (Python) calls the `_matter` C module
(`native/micropython/matter_module.c`), which calls the C++ bridge in
`native/src/`, which drives ESP-Matter/CHIP. Comments below name the native
file each call lands in next. Full call-path diagrams:
`firmware-packages/matter/ARCHITECTURE.md`.
"""

import os
import time
from collections import namedtuple

import machine
import neopixel
from color import matter_to_triple, publish_triple

import matter

# Pin map for this board. led_pin drives the onboard WS2812. Only ESP32-S3 is
# supported, so any other chip is a build error, not a fallback case.
Board = namedtuple("Board", ("name", "led_pin", "pixel_count"))
_machine = os.uname().machine
if "ESP32S3" not in _machine:
    raise RuntimeError(f"unsupported board: {_machine}")
BOARD = Board(name="ESP32-S3-Zero", led_pin=21, pixel_count=1)

BOOT_COLOR = (25, 25, 25)

# Tick the current colour was commanded on. Ordering only, never written to
# flash. A list cell so `show()` below can update it without `global`.
_stamp = [0]


def render(color: tuple) -> None:
    """Drive the strip. Every hardware touch in this project is these two lines."""
    pixel[0] = color
    pixel.write()


def show(color: tuple, stamp: int) -> None:
    """Render a colour unless a newer one was already commanded.

    Callbacks can run out of order, so an older decision could otherwise
    overwrite a newer one. Comparing stamps stops that.

    Args:
        color: Red, green, and blue channel values in the range 0-255.
        stamp: `time.ticks_ms()` reading from when the colour was commanded.
            Equal stamps render, so the boot baseline still shows.
    """
    if time.ticks_diff(stamp, _stamp[0]) < 0:
        return
    _stamp[0] = stamp
    render(color)


def set_color(color: tuple) -> None:
    """Show a colour locally, then publish it to Matter.

    Colour is published before power, so a controller never briefly sees the
    old colour lit.

    Args:
        color: Red, green, and blue channel values in the range 0-255.
    """
    show(color, time.ticks_ms())
    # Below: Endpoint.publish -> _matter.attribute_publish -> request.cpp
    # matter_attribute_publish -- a bounded round trip onto the CHIP task
    # (ARCHITECTURE.md "A local change going out").
    publish_triple(endpoint, color)
    if not endpoint.on:
        endpoint.on = True


def on_remote_write(_event: object) -> None:
    """Show the colour a controller just wrote.

    The event only names the one attribute that changed, so the full colour
    is read back from the endpoint instead of computed from the event.

    Args:
        _event: Unused. Only wakes this callback.
    """
    show(matter_to_triple(endpoint), time.ticks_ms())


pixel = neopixel.NeoPixel(machine.Pin(BOARD.led_pin, machine.Pin.OUT), BOARD.pixel_count)

# Nothing is painted yet. We can't know this board's colour until start()
# finishes, and a guess now would just flash before the real colour lands.
# Leaving the strip alone also means a soft reset keeps its last colour
# through the restart.

# Taken before start(), which can deliver queued controller writes before it
# returns. Those writes get a later stamp, so they win over the restored
# colour below.
_stamp[0] = time.ticks_ms()

# Node() -> matter/node.py Node.__init__ -> _matter.node_create() ->
# stack.cpp matter_node_create() -> esp_matter::node::create(). Runs directly
# on this task -- there's no CHIP task yet to schedule onto (ARCHITECTURE.md
# "Boot").
node = matter.Node()

# create_endpoint() crosses into stack.cpp the same way: matter_endpoint_create(),
# then matter_attribute_set_initial() for each attribute named in initial.
#
# No initial state passed: every attribute here is one a controller owns, and
# pinning one now would overwrite what persistence is about to restore.
endpoint = node.create_endpoint(matter.EndpointType.EXTENDED_COLOR_LIGHT)

# on_write() just stores this callback on the Python Endpoint
# (matter/endpoint.py) -- nothing native happens here. It fires later from
# Node._drain (ARCHITECTURE.md "A controller write coming in").
endpoint.on_write(on_remote_write)

# start() -> _matter.start() -> stack.cpp matter_stack_start() ->
# esp_matter::start(): the CHIP task comes up here. After this line, native
# calls schedule a Request onto that task and block on a semaphore
# (native/src/request.cpp) instead of running directly.
node.start()

# Picks the boot colour. A commissioned board restores its last colour
# (black if it was off). An uncommissioned board shows BOOT_COLOR instead, as
# a sign it's waiting to be paired. Either way, a write that landed during
# start() has a later stamp and wins.
#
# fabrics() takes the same request.cpp round trip as the writes above, just
# reading the fabric table instead of publishing an attribute.
if node.fabrics():
    show(matter_to_triple(endpoint), _stamp[0])
else:
    show(BOOT_COLOR, _stamp[0])
