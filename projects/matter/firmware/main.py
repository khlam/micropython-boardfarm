"""Expose the ESP32-S3-Zero's onboard WS2812 as a Matter Extended Color Light.

Read this file top to bottom to audit the firmware: the board's pins, the
hardware boot() creates, the Matter loop and its states, then set_color() for
the REPL. Every output is chosen here:

- The pixel: StatusLed shows the Matter state, or the light's own colour once
  the node is operational and connected. poll_matter() feeds it each controller
  write and state change; set_color() feeds it a local colour.
- The light's Matter attributes: set_color(), the only local writer.
- JSON lines over USB serial: each emit(), emit_state(), and error() call below.

Interrupting the loop with Ctrl-C leaves ``pixel``, ``status``, ``node``,
``endpoint``, and ``set_color`` in scope, so a serial session can drive the
light and administer the node. The ``matter`` package README diagrams how each
call into it reaches ESP-Matter.
"""

import os
import time
from collections import namedtuple

import machine
import neopixel
from color import matter_to_triple, publish_triple

import matter
from matter.emit import emit, emit_state, error
from matter.status_led import StatusLed

# Pin map for this board. ``led_pin`` drives the onboard WS2812. Only ESP32-S3
# is supported, so any other chip is a build error, not a fallback case.
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


def boot() -> tuple:
    """Create the pixel and the Matter light, and start Matter.

    Returns:
        The pixel, its status LED, the started node, and the light's endpoint.
    """
    pixel = neopixel.NeoPixel(machine.Pin(BOARD.led_pin, machine.Pin.OUT), BOARD.pixel_count)
    # Dim white until the first poll reports the Matter state.
    status = StatusLed(pixel, STATUS_LEVEL)

    node = matter.Node()
    # No initial values: a controller owns every attribute, and pinning one
    # would overwrite what start() restores from flash.
    endpoint = node.create_endpoint(matter.EndpointType.EXTENDED_COLOR_LIGHT)
    # Blocks while ESP-Matter comes up, retrying its first reads every 250 ms
    # up to 40 times; a stack that never answers raises OSError. A value in
    # flash the light's schema refuses leaves that attribute at its default.
    for _rejected in node.start():
        error("python_validation", "restored value rejected by schema")
    emit({"event": "matter", "state": "ready"})
    emit({"event": "fabric", "state": node.state.fabric})

    # The last controller-owned colour, shown once the node is operational and
    # connected.
    status.set_application(matter_to_triple(endpoint))
    return pixel, status, node, endpoint


def poll_matter(node: matter.Node, endpoint: matter.Endpoint, status: StatusLed) -> None:
    """Poll Matter every 50 ms, stepping the pixel's blink on each pass.

    States:
        polling: each controller write to the light shows its colour, each
            change of Matter state goes to the pixel and out as JSON lines,
            and a failed pairing attempt flashes the pixel red.
        failing: the pixel keeps its pattern. The first failed poll of a run
            is reported as a ``matter_poll`` error.

    Args:
        node: The started Matter node.
        endpoint: The light's endpoint.
        status: The status pixel.
    """
    failing = False
    while True:
        try:
            events = node.poll()
        except OSError as exception:
            if not failing:
                error("matter_poll", str(exception))
            failing = True
        else:
            failing = False
            for event in events:
                _show(event, endpoint, status)
            status.set_state(node.state)
        status.tick()
        time.sleep_ms(POLL_INTERVAL_MS)


def _show(event: object, endpoint: matter.Endpoint, status: StatusLed) -> None:
    """Send one polled Matter event to the pixel and serial.

    Args:
        event: A change of Matter state, a controller write to the light, or a
            controller value the light's schema refused.
        endpoint: The light's endpoint.
        status: The status pixel.
    """
    if isinstance(event, matter.StateEvent):
        emit_state(event)
        if event.failed:
            status.fail()
    elif isinstance(event, matter.RejectedValue):
        error("python_validation", "remote value rejected by schema")
    else:
        # A write to the light, the node's only endpoint. The whole endpoint
        # is synchronized by now, so a batch of colour writes shows as one
        # colour.
        status.set_application(matter_to_triple(endpoint))


def set_color(color: tuple) -> None:
    """Show a colour on the pixel, then publish it to Matter. For the REPL.

    The pixel shows the colour only once the node is operational and
    connected; until then it keeps showing the Matter state. Colour is
    published before power, so a controller never briefly sees the old colour
    lit. Uses the ``status`` and ``endpoint`` that boot() left in scope.

    Args:
        color: Red, green, and blue channel values in the range 0-255.
    """
    status.set_application(color)
    status.tick()
    publish_triple(endpoint, color)
    lit = endpoint.level != 0
    if endpoint.on != lit:
        endpoint.set(on=lit)


# After Ctrl-C these stay in scope for the REPL, alongside set_color().
pixel, status, node, endpoint = boot()
poll_matter(node, endpoint, status)
