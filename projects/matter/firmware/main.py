"""Expose the ESP32-S3-Zero onboard WS2812 through ESP-Matter.

Definitions first, boot sequence at the bottom. The module polls Matter every
50 ms after startup. Interrupting that loop leaves `pixel`, `node`, `endpoint`,
and the functions below in scope, so a serial session can drive the light and
administer the node.

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
from matter.emit import error

# Pin map for this board. led_pin drives the onboard WS2812. Only ESP32-S3 is
# supported, so any other chip is a build error, not a fallback case.
Board = namedtuple("Board", ("name", "led_pin", "pixel_count"))
_machine = os.uname().machine
if "ESP32S3" not in _machine:
    raise RuntimeError(f"unsupported board: {_machine}")
BOARD = Board(name="ESP32-S3-Zero", led_pin=21, pixel_count=1)

# One colour per state a node can be in before it is paired, because the
# failures worth catching are the ones where it stops advertising: a node nobody
# can reach has to look different from one waiting to be scanned.
BOOT_COLOR = (25, 25, 25)
WINDOW_COLOR = (25, 0, 25)
SESSION_COLOR = (0, 25, 25)
FAILED_COLOR = (25, 0, 0)
STALLED_COLOR = (25, 12, 0)
OFF_COLOR = (0, 0, 0)
POLL_INTERVAL_MS = 50

# Mutable cells retain the latest state delivered by cooperative polling.
_commissioned = [False]
_commissioning_state = [None]
_session_active = [False]

# Last controller-owned colour the event loop actually rendered.
_last_remote_color = [None]


def render(color: tuple) -> None:
    """Drive the strip. Every hardware touch in this project is these two lines."""
    pixel[0] = color
    pixel.write()


def set_color(color: tuple) -> None:
    """Show a colour locally, then publish it to Matter.

    Colour is published before power, so a controller never briefly sees the
    old colour lit.

    Args:
        color: Red, green, and blue channel values in the range 0-255.
    """
    render(color)
    # Below: Endpoint.set -> _matter.attributes_publish -> request.cpp
    # matter_attributes_publish -- a bounded round trip onto the CHIP task
    # (ARCHITECTURE.md "Local publication").
    publish_triple(endpoint, color)
    lit = endpoint.level != 0
    if endpoint.on != lit:
        endpoint.set(on=lit)


def _show_controller_color() -> None:
    """Show the synchronized controller colour unless it repeats the last one shown.

    A poll can carry several attributes for one color command. Reading the
    fully synchronized endpoint collapses that batch to one render; comparing
    against the last color drops its remaining write events before they reach
    the bit-banged NeoPixel write.
    """
    color = matter_to_triple(endpoint)
    if color == _last_remote_color[0]:
        return
    _last_remote_color[0] = color
    render(color)


def _pairing_color() -> tuple:
    """Return the colour describing where pairing currently stands.

    A closed window is the ambiguous one: it closes both when a commissioner
    takes it and when it simply runs out. The first is the middle of a healthy
    pairing, the second leaves the node advertising nothing — so the tracked
    session, not the closure, decides which colour it gets.
    """
    state = _commissioning_state[0]
    if state == matter.Commissioning.FAILED:
        return FAILED_COLOR
    if state == matter.Commissioning.STARTED:
        return SESSION_COLOR
    if state == matter.Commissioning.OPENED:
        return WINDOW_COLOR
    if _session_active[0]:
        return SESSION_COLOR
    if state == matter.Commissioning.CLOSED:
        return STALLED_COLOR
    return BOOT_COLOR


def _show_state() -> None:
    """Render whichever of pairing state or controller-owned colour applies.

    Pairing wins while it is in flight, on a commissioned node too: an owner
    adding a second controller wants to watch that, not the light. Once the
    attempt settles, a paired node goes back to showing its colour.
    """
    pairing = _session_active[0] or _commissioning_state[0] in (
        matter.Commissioning.OPENED,
        matter.Commissioning.STARTED,
        matter.Commissioning.FAILED,
    )
    if _commissioned[0] and not pairing:
        render(matter_to_triple(endpoint))
        return
    render(_pairing_color())


def _finish_commissioning() -> None:
    """Turn the newly commissioned accessory off locally and in Matter."""
    render(OFF_COLOR)
    endpoint.set(on=False)


def handle_events(events: tuple) -> None:
    """Apply one explicit batch returned by :meth:`matter.Node.poll`.

    Args:
        events: Revision-ordered controller and commissioning events.
    """
    for event in events:
        if isinstance(event, matter.WriteEvent):
            if event.endpoint is endpoint:
                _show_controller_color()
            continue
        _on_commissioning(event)


def _on_commissioning(event: object) -> None:
    """Record one commissioning transition and render the state it leaves.

    A failure is rendered but not latched. The Matter package reopens a window
    whenever an unpaired node would otherwise stop advertising, so red is
    followed by purple within moments — and a red that stays red is then a
    genuine finding rather than a colour nothing was able to clear.

    Args:
        event: :class:`matter.CommissioningEvent` delivered by the node.
    """
    state = event.state
    _commissioning_state[0] = state
    if state == matter.Commissioning.STARTED:
        _session_active[0] = True
    elif state in (matter.Commissioning.COMPLETE, matter.Commissioning.FAILED):
        _session_active[0] = False
    if state == matter.Commissioning.COMPLETE:
        _commissioned[0] = True
        _finish_commissioning()
        return
    _show_state()


pixel = neopixel.NeoPixel(machine.Pin(BOARD.led_pin, machine.Pin.OUT), BOARD.pixel_count)

# White is the only state known before the stack starts.
render(BOOT_COLOR)

# Node() -> matter/node.py Node.__init__ -> _matter.node_create() ->
# stack.cpp matter_node_create() -> esp_matter::node::create(). Runs directly
# on this task -- there's no CHIP task yet to schedule onto (ARCHITECTURE.md
# "Startup and restoration").
node = matter.Node()

# create_endpoint() crosses into stack.cpp the same way: matter_endpoint_create(),
# then matter_attribute_set_initial() for each attribute named in initial.
#
# No initial state passed: every attribute here is one a controller owns, and
# pinning one now would overwrite what persistence is about to restore.
endpoint = node.create_endpoint(matter.EndpointType.EXTENDED_COLOR_LIGHT)

# start() -> _matter.start() -> stack.cpp matter_stack_start() ->
# esp_matter::start(): the CHIP task comes up here. After this line, native
# calls schedule a Request onto that task and block on a semaphore
# (native/src/request.cpp) instead of running directly.
node.start()

# A commissioned board restores its last controller-owned colour. An
# uncommissioned board shows the boot baseline until the first poll delivers
# retained pairing state. fabrics() takes the same bounded request.cpp round
# trip as the attribute writes above.
_commissioned[0] = bool(node.fabrics())
_show_state()


def run() -> None:
    """Poll Matter cooperatively, reporting each failure period once."""
    failure_reported = False
    while True:
        try:
            events = node.poll()
            handle_events(events)
        except OSError as exception:
            if not failure_reported:
                error("matter_poll", str(exception))
            failure_reported = True
        else:
            failure_reported = False
        time.sleep_ms(POLL_INTERVAL_MS)


run()
