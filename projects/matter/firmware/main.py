"""Expose the ESP32-S3-Zero onboard WS2812 through ESP-Matter.

Definitions first, boot sequence at the bottom. The module polls Matter every
50 ms after startup. Interrupting that loop leaves `pixel`, `status`, `node`,
`endpoint`, and the functions below in scope, so a serial session can drive the
light and administer the node.

The pixel follows the Matter device model. While the node is pairing, unpaired,
or off Wi-Fi, `status` shows that state; once it is operational and connected,
the pixel shows the light's own colour.

Calls into `matter.Node`, `Node.start`, or an `Endpoint` attribute leave this
file for compiled code: `matter/` (Python) calls the `matter_native` C module
(`native/micropython/matter_module.c`), which calls the C++ bridge in
`native/src/`, which drives ESP-Matter/CHIP. Comments below name the native
file each call lands in next. Call-path diagrams:
`firmware-packages/matter/README.md`.
"""

import os
import time
from collections import namedtuple

import machine
import neopixel
from color import matter_to_triple, publish_triple

import matter
from matter.emit import error
from matter_status_led import StatusLed

# Pin map for this board. led_pin drives the onboard WS2812. Only ESP32-S3 is
# supported, so any other chip is a build error, not a fallback case.
Board = namedtuple("Board", ("name", "led_pin", "pixel_count"))
_machine = os.uname().machine
if "ESP32S3" not in _machine:
    raise RuntimeError(f"unsupported board: {_machine}")
BOARD = Board(name="ESP32-S3-Zero", led_pin=21, pixel_count=1)

# Status patterns are capped at ten percent of full scale, because a status
# light has no business being the brightest thing in the room. Only a
# controller-commanded level may reach maximum.
STATUS_LEVEL = 25
POLL_INTERVAL_MS = 50


def set_color(color: tuple) -> None:
    """Show a colour locally, then publish it to Matter.

    Colour is published before power, so a controller never briefly sees the
    old colour lit. The pixel shows the colour only once the node is
    operational and connected; until then it keeps showing the Matter state.

    Args:
        color: Red, green, and blue channel values in the range 0-255.
    """
    status.set_application(color)
    status.tick()
    # Below: Endpoint.set -> matter_native.attributes_publish -> request.cpp
    # matter_attributes_publish -- a bounded round trip onto the CHIP task.
    publish_triple(endpoint, color)
    lit = endpoint.level != 0
    if endpoint.on != lit:
        endpoint.set(on=lit)


def handle_events(events: tuple) -> None:
    """Apply one explicit batch returned by :meth:`matter.Node.poll`.

    Args:
        events: Revision-ordered controller writes and device-state changes.
    """
    for event in events:
        if isinstance(event, matter.StateEvent):
            if event.failed:
                status.fail()
        elif event.endpoint is endpoint:
            # The whole endpoint is synchronized by now, so the batch behind one
            # colour command collapses to a single colour.
            status.set_application(matter_to_triple(endpoint))
    status.set_state(node.state)


pixel = neopixel.NeoPixel(machine.Pin(BOARD.led_pin, machine.Pin.OUT), BOARD.pixel_count)

# Dim white until the first poll reports the Matter state.
status = StatusLed(pixel, STATUS_LEVEL)

# Node() -> matter/node.py Node.__init__ -> matter_native.node_create() ->
# stack.cpp matter_node_create() -> esp_matter::node::create(). Runs directly
# on this task -- there's no CHIP task yet to schedule onto.
node = matter.Node()

# create_endpoint() crosses into stack.cpp the same way: matter_endpoint_create(),
# then matter_attribute_set_initial() for each attribute named in initial.
#
# No initial state passed: every attribute here is one a controller owns, and
# pinning one now would overwrite what persistence is about to restore.
endpoint = node.create_endpoint(matter.EndpointType.EXTENDED_COLOR_LIGHT)

# start() -> matter_native.start() -> stack.cpp matter_stack_start() ->
# esp_matter::start(): the CHIP task comes up here. After this line, native
# calls schedule a Request onto that task and block on a semaphore
# (native/src/request.cpp) instead of running directly. start() also counts the
# restored fabrics, which seeds node.state.
node.start()

# The last controller-owned colour, shown once the node is operational and on
# the network.
status.set_application(matter_to_triple(endpoint))


def run() -> None:
    """Poll Matter cooperatively, reporting each failure period once."""
    failure_reported = False
    while True:
        try:
            handle_events(node.poll())
        except OSError as exception:
            if not failure_reported:
                error("matter_poll", str(exception))
            failure_reported = True
        else:
            failure_reported = False
        status.tick()
        time.sleep_ms(POLL_INTERVAL_MS)


run()
