"""Expose a WS2812B strip as a Matter color light with pattern switches.

Definitions first, boot sequence at the bottom. The module runs once at boot,
then drops to the REPL with `strip`, `node`, `endpoint`, and the functions
below still in scope, so a serial session can drive the light and administer
the node.

The commissioning-status light show and boot-cache read/write live in
`commissioning_status.py` and `boot_cache.py`; `patterns.py` owns animation
state without claiming hardware. This file owns both NeoPixel devices and
routes local RGB, light-attribute, and virtual On/Off writes to those helpers.

Calls into `matter.Node`, `Node.start`, or an `Endpoint` attribute leave this
file for compiled code that drives ESP-Matter/CHIP; see
`firmware-packages/matter/ARCHITECTURE.md` for the call-path diagrams.
"""

import os
import time
from collections import namedtuple

import boot_cache
import commissioning_status
import machine
import neopixel
import patterns
from color import matter_to_triple, publish_triple

import matter

# data_pin is the external strip's data line, kept separate from the onboard
# WS2812. Only ESP32-S3 is supported, so any other chip is a build error.
Board = namedtuple("Board", ("name", "data_pin"))
_machine = os.uname().machine
if "ESP32S3" not in _machine:
    raise RuntimeError(f"unsupported board: {_machine}")
BOARD = Board(name="ESP32-S3-Zero", data_pin=4)

LED_COUNT = 20
STATUS_LED_PIN = 21  # ESP32-S3-Zero onboard WS2812

_COLOR_ATTRIBUTES = (
    matter.Attributes.CURRENT_HUE,
    matter.Attributes.CURRENT_SATURATION,
    matter.Attributes.CURRENT_X,
    matter.Attributes.CURRENT_Y,
    matter.Attributes.COLOR_TEMPERATURE_MIREDS,
    matter.Attributes.COLOR_MODE,
    matter.Attributes.ENHANCED_COLOR_MODE,
)


def render(color: tuple) -> None:
    """Drive the external strip. See `render_status` for the onboard WS2812."""
    for i in range(LED_COUNT):
        strip[i] = color
    strip.write()


def render_status(color: tuple) -> None:
    """Drive the onboard WS2812. The only other hardware touch in this project."""
    status_led[0] = color
    status_led.write()


def set_color(color: tuple) -> None:
    """Show a colour locally, then publish it to Matter.

    Colour is published before power, so a controller never briefly sees the
    old colour lit.

    Args:
        color: Red, green, and blue channel values in the range 0-255.
    """
    patterns.reset_color(color)
    # Below: Endpoint.publish -> _matter.attribute_publish -> request.cpp
    # matter_attribute_publish -- a bounded round trip onto the CHIP task
    # (ARCHITECTURE.md "A local change going out").
    publish_triple(endpoint, color)
    lit = endpoint.level != 0
    if endpoint.on != lit:
        endpoint.on = lit
    if commissioning_status.is_commissioned():
        boot_cache.save(on=lit, color=color)


def on_remote_write(event: object) -> None:
    """Apply a controller light write without discarding brightness patterns.

    Color Control writes select a steady light even when the resulting RGB
    triple repeats. Power and level writes refresh the selected pattern, with
    an off-to-on transition restarting its phase.

    Args:
        event: Controller-originated Matter attribute write.
    """
    color = matter_to_triple(endpoint)
    if event.cluster == matter.Clusters.COLOR_CONTROL and event.attribute in _COLOR_ATTRIBUTES:
        patterns.reset_color()
    else:
        restarted = (
            event.cluster == matter.Clusters.ON_OFF
            and event.attribute == matter.Attributes.ON_OFF
            and endpoint.on
        )
        patterns.refresh(restart=restarted)
    if commissioning_status.is_commissioned():
        boot_cache.save(on=endpoint.on, color=color)


strip = neopixel.NeoPixel(machine.Pin(BOARD.data_pin, machine.Pin.OUT), LED_COUNT)
status_led = neopixel.NeoPixel(machine.Pin(STATUS_LED_PIN, machine.Pin.OUT), 1)
commissioning_status.bind_strip_render(render)
commissioning_status.bind_status_render(render_status)
commissioning_status.start_animator()

# A previously-commissioned board that has shown a real colour restores that
# colour on the strip immediately, before Matter's own (much slower) native
# restore is even reachable -- see commissioning_status.py's module
# docstring. Everything else shows today's dim-white boot colour on the
# onboard status LED and explicitly holds the strip off, since a warm reset
# (no power cycle) would otherwise leave a WS2812 strip showing whatever it
# was last driven to.
_startup_stamp = time.ticks_ms()
_cached = boot_cache.load()
if _cached is not None:
    commissioning_status.show_strip(tuple(_cached["color"]), _startup_stamp)
else:
    commissioning_status.show_status(commissioning_status.BOOT_COLOR, _startup_stamp)
    commissioning_status.show_strip(commissioning_status.OFF_COLOR, _startup_stamp)

node = matter.Node()

# No initial state passed: every attribute here is one a controller owns, and
# pinning one now would overwrite what persistence is about to restore.
endpoint = node.create_endpoint(matter.EndpointType.EXTENDED_COLOR_LIGHT)
pattern_endpoints = tuple(
    node.create_endpoint(matter.EndpointType.ON_OFF_LIGHT) for _label in patterns.PATTERN_LABELS
)
commissioning_status.bind_node(node, endpoint)

patterns.bind(
    light=endpoint,
    switches=pattern_endpoints,
    buffer=strip.buf,
    order=strip.ORDER,
    write=strip.write,
    available=commissioning_status.strip_available,
    pixel_count=LED_COUNT,
)
commissioning_status.bind_strip_release(patterns.resume)
patterns.start()

endpoint.on_write(on_remote_write)
for pattern_endpoint in pattern_endpoints:
    pattern_endpoint.on_write(patterns.select_remote)

# Queued transitions may be delivered before start() returns. The callback
# records any action that requires a started node and show_post_start_state()
# completes it below.
node.on_commissioning(commissioning_status.on_commissioning)

node.start()

# Restore a persisted pattern only for a light that also restored on. This
# runs before commissioning releases its strip overlay, so the first
# application-owned frame already reflects the reconciled mode.
patterns.restore()

# A commissioned board restores its last controller-owned colour, applied
# uniformly across the strip, and shows dim green on the onboard LED. An
# uncommissioned board settles on steady cyan across both LEDs unless a
# queued window/session event is still pending. fabrics() takes the same
# bounded request.cpp round trip as the attribute writes above.
commissioning_status.show_post_start_state(
    has_fabric=bool(node.fabrics()), startup_stamp=_startup_stamp
)
