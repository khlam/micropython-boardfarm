"""The README's contract, run through the whole main.py on the virtual bench.

Each row boots the firmware with a start state, delivers inputs at virtual
times, stops its loop at ``until_ms``, and lists everything that left it: the
project's JSON lines and every colour written to the pixel.

Matter is polled on every 50 ms mark, starting at boot. Inputs due at an
instant reach the stack before that instant's poll.
"""

import contextlib
from collections import namedtuple

import machine
import pytest
from color_light_bench import (
    LevelWrite,
    LightRemoved,
    LightSet,
    PairingCompletes,
    PairingFails,
    PairingStarts,
    PollFault,
    StoredLight,
    WifiDown,
    WifiUp,
    WindowCloses,
    WindowOpens,
)

# Light colours a controller left in flash, and what the pixel shows for them.
GREEN_AT_TEN_PERCENT = StoredLight(on=True, level=25, hue=85, saturation=254)
LEVEL_OUTSIDE_THE_SCHEMA = StoredLight(on=True, level=255, hue=0, saturation=254)
GREEN = (0, 25, 0)
FULL_RED = (255, 0, 0)

# Pixel colours at the status brightness of 25, ten percent of full scale.
BOOT_WHITE = (25, 25, 25)
PAIRABLE_PURPLE = (25, 0, 25)
PAIRING_CYAN = (0, 25, 25)
FAILED_RED = (25, 0, 0)
AMBER = (25, 12, 0)
OFF = (0, 0, 0)

# JSON lines.
READY = {"event": "matter", "state": "ready"}
UNCOMMISSIONED = {"event": "fabric", "state": "uncommissioned"}
COMMISSIONING = {"event": "fabric", "state": "commissioning"}
OPERATIONAL = {"event": "fabric", "state": "operational"}
CONNECTED = {"event": "network", "state": "connected"}
DISCONNECTED = {"event": "network", "state": "disconnected"}
WINDOW_OPENED = {"event": "commissioning_window", "state": "opened"}
WINDOW_CLOSED = {"event": "commissioning_window", "state": "closed"}
PAIRING_FAILED = {"event": "commissioning", "state": "failed"}
POLL_ERROR = {
    "event": "error",
    "component": "matter_poll",
    "message": "[Errno 5] injected snapshot failure",
}
RESTORED_REJECTED = {
    "event": "error",
    "component": "python_validation",
    "message": "restored value rejected by schema",
}
REMOTE_REJECTED = {
    "event": "error",
    "component": "python_validation",
    "message": "remote value rejected by schema",
}
# A paired board on Wi-Fi: ready, the restored fabric, then the link at the first poll.
PAIRED_ONLINE_BOOT = (READY, OPERATIONAL, CONNECTED)

# Attribute batches set_color() publishes, by name.
GREEN_ATTRIBUTES = {
    "hue": 85,
    "saturation": 254,
    "color_mode": 0,
    "enhanced_color_mode": 0,
    "level": 25,
}
RED_ATTRIBUTES = {**GREEN_ATTRIBUTES, "hue": 0}
BLACK_ATTRIBUTES = {**GREEN_ATTRIBUTES, "hue": 0, "saturation": 0, "level": 0}

Case = namedtuple(
    "Case",
    (
        "id",
        # Start state.
        "paired",
        "online",
        "stored_light",
        # Inputs.
        "inputs",
        "until_ms",
        # Outputs.
        "lines",
        "pixel",
    ),
)

ReplCase = namedtuple(
    "ReplCase",
    (
        "id",
        # Start state.
        "paired",
        "online",
        "stored_light",
        "inputs",
        # Colours typed at the REPL, each passed to set_color().
        "typed",
        # Outputs.
        "published",
        "pixel",
    ),
)

Board = namedtuple("Board", ("id", "machine", "error", "pins"))


@pytest.mark.parametrize(
    "case",
    [
        Case(
            # Purple blinks 500 ms on, 500 ms off.
            id="unpaired-window-open-blinks-purple-slowly",
            paired=False,
            online=False,
            stored_light=None,
            inputs=(WindowOpens(at_ms=0),),
            until_ms=1100,
            lines=(READY, UNCOMMISSIONED, WINDOW_OPENED),
            pixel=(BOOT_WHITE, PAIRABLE_PURPLE, OFF, PAIRABLE_PURPLE),
        ),
        Case(
            id="unpaired-without-window-shows-solid-amber",
            paired=False,
            online=False,
            stored_light=None,
            inputs=(),
            until_ms=1100,
            lines=(READY, UNCOMMISSIONED),
            pixel=(BOOT_WHITE, AMBER),
        ),
        Case(
            # The README's Apple Home sequence. Cyan blinks 100 ms on, 100 ms
            # off, through the closing window and the Wi-Fi link, until the
            # light shows: off, so dark.
            id="unpaired-apple-home-pairs-blinking-cyan-then-shows-the-light-dark",
            paired=False,
            online=False,
            stored_light=None,
            inputs=(
                WindowOpens(at_ms=0),
                PairingStarts(at_ms=1000),
                WindowCloses(at_ms=1050),
                WifiUp(at_ms=1100),
                PairingCompletes(at_ms=1500),
            ),
            until_ms=1550,
            lines=(
                READY,
                UNCOMMISSIONED,
                WINDOW_OPENED,
                COMMISSIONING,
                WINDOW_CLOSED,
                CONNECTED,
                OPERATIONAL,
            ),
            pixel=(
                BOOT_WHITE,
                PAIRABLE_PURPLE,
                OFF,
                PAIRING_CYAN,
                OFF,
                PAIRING_CYAN,
                OFF,
                PAIRING_CYAN,
                OFF,
            ),
        ),
        Case(
            # Red flashes 200 ms on, 200 ms off, three times from 600 ms.
            id="unpaired-failed-pairing-flashes-red-three-times-then-blinks-purple",
            paired=False,
            online=False,
            stored_light=None,
            inputs=(WindowOpens(at_ms=0), PairingStarts(at_ms=500), PairingFails(at_ms=600)),
            until_ms=1850,
            lines=(
                READY,
                UNCOMMISSIONED,
                WINDOW_OPENED,
                COMMISSIONING,
                PAIRING_FAILED,
                UNCOMMISSIONED,
            ),
            pixel=(
                BOOT_WHITE,
                PAIRABLE_PURPLE,
                PAIRING_CYAN,
                FAILED_RED,
                OFF,
                FAILED_RED,
                OFF,
                FAILED_RED,
                OFF,
                PAIRABLE_PURPLE,
            ),
        ),
        Case(
            # Amber blinks 500 ms on, 500 ms off.
            id="paired-reboot-blinks-amber-until-wifi-joins-then-shows-the-stored-colour",
            paired=True,
            online=False,
            stored_light=GREEN_AT_TEN_PERCENT,
            inputs=(WifiUp(at_ms=1000),),
            until_ms=1050,
            lines=PAIRED_ONLINE_BOOT,
            pixel=(BOOT_WHITE, AMBER, OFF, GREEN),
        ),
        Case(
            id="operational-wifi-drops-blinks-amber-until-it-returns",
            paired=True,
            online=True,
            stored_light=GREEN_AT_TEN_PERCENT,
            inputs=(WifiDown(at_ms=1000), WifiUp(at_ms=1600)),
            until_ms=1650,
            lines=(*PAIRED_ONLINE_BOOT, DISCONNECTED, CONNECTED),
            pixel=(BOOT_WHITE, GREEN, AMBER, OFF, GREEN),
        ),
        Case(
            # Status colours stop at ten percent; a controller's level does not.
            id="operational-controller-sets-full-red-and-the-pixel-shows-it-at-full-brightness",
            paired=True,
            online=True,
            stored_light=None,
            inputs=(LightSet(at_ms=1000, on=True, level=254, hue=0, saturation=254),),
            until_ms=1050,
            lines=PAIRED_ONLINE_BOOT,
            pixel=(BOOT_WHITE, OFF, FULL_RED),
        ),
        Case(
            id="operational-controller-switches-the-light-off-and-the-pixel-goes-dark",
            paired=True,
            online=True,
            stored_light=GREEN_AT_TEN_PERCENT,
            inputs=(LightSet(at_ms=1000, on=False, level=25, hue=85, saturation=254),),
            until_ms=1050,
            lines=PAIRED_ONLINE_BOOT,
            pixel=(BOOT_WHITE, GREEN, OFF),
        ),
        Case(
            id="operational-window-for-another-controller-blinks-purple-until-it-closes",
            paired=True,
            online=True,
            stored_light=GREEN_AT_TEN_PERCENT,
            inputs=(WindowOpens(at_ms=1000), WindowCloses(at_ms=2000)),
            until_ms=2050,
            lines=(*PAIRED_ONLINE_BOOT, WINDOW_OPENED, WINDOW_CLOSED),
            pixel=(BOOT_WHITE, GREEN, PAIRABLE_PURPLE, OFF, GREEN),
        ),
        Case(
            id="operational-home-removes-the-light-and-it-blinks-purple-again",
            paired=True,
            online=True,
            stored_light=GREEN_AT_TEN_PERCENT,
            inputs=(LightRemoved(at_ms=1000),),
            until_ms=1050,
            lines=(*PAIRED_ONLINE_BOOT, UNCOMMISSIONED, WINDOW_OPENED),
            pixel=(BOOT_WHITE, GREEN, PAIRABLE_PURPLE),
        ),
        Case(
            # The polls at 1000 and 1050 ms fail as one run; 2000 ms starts another.
            id="operational-poll-failures-are-reported-once-per-run",
            paired=True,
            online=True,
            stored_light=GREEN_AT_TEN_PERCENT,
            inputs=(PollFault(at_ms=1000), PollFault(at_ms=1050), PollFault(at_ms=2000)),
            until_ms=2050,
            lines=(*PAIRED_ONLINE_BOOT, POLL_ERROR, POLL_ERROR),
            pixel=(BOOT_WHITE, GREEN),
        ),
        Case(
            # The light keeps its level of 254, so the stored red shows at full.
            id="stored-level-outside-the-schema-is-reported-before-ready",
            paired=True,
            online=True,
            stored_light=LEVEL_OUTSIDE_THE_SCHEMA,
            inputs=(),
            until_ms=50,
            lines=(RESTORED_REJECTED, *PAIRED_ONLINE_BOOT),
            pixel=(BOOT_WHITE, FULL_RED),
        ),
        Case(
            id="operational-controller-level-outside-the-schema-is-reported-and-ignored",
            paired=True,
            online=True,
            stored_light=GREEN_AT_TEN_PERCENT,
            inputs=(LevelWrite(at_ms=1000, level=255),),
            until_ms=1050,
            lines=(*PAIRED_ONLINE_BOOT, REMOTE_REJECTED),
            pixel=(BOOT_WHITE, GREEN),
        ),
    ],
    ids=lambda case: case.id,
)
def test_scenario_readme_contract(run_light, case):
    """Run one README contract line through main.py and check everything that left it."""
    outcome = run_light(
        paired=case.paired,
        online=case.online,
        stored_light=case.stored_light,
        inputs=case.inputs,
        until_ms=case.until_ms,
    )

    assert outcome.lines == case.lines
    assert outcome.pixel == case.pixel


@pytest.mark.parametrize(
    "case",
    [
        ReplCase(
            id="unpaired-green-publishes-colour-then-power-and-stays-behind-purple",
            paired=False,
            online=False,
            stored_light=None,
            inputs=(WindowOpens(at_ms=0),),
            typed=(GREEN,),
            published=(GREEN_ATTRIBUTES, {"on": True}),
            pixel=(BOOT_WHITE, PAIRABLE_PURPLE),
        ),
        ReplCase(
            id="operational-dark-light-set-to-green-shows-its-exact-bytes-and-switches-on",
            paired=True,
            online=True,
            stored_light=None,
            inputs=(),
            typed=(GREEN,),
            published=(GREEN_ATTRIBUTES, {"on": True}),
            pixel=(BOOT_WHITE, OFF, GREEN),
        ),
        ReplCase(
            id="operational-lit-light-set-to-red-leaves-power-alone",
            paired=True,
            online=True,
            stored_light=GREEN_AT_TEN_PERCENT,
            inputs=(),
            typed=((25, 0, 0),),
            published=(RED_ATTRIBUTES,),
            pixel=(BOOT_WHITE, GREEN, (25, 0, 0)),
        ),
        ReplCase(
            id="operational-dark-light-set-to-black-stays-off",
            paired=True,
            online=True,
            stored_light=None,
            inputs=(),
            typed=(OFF,),
            published=(BLACK_ATTRIBUTES,),
            pixel=(BOOT_WHITE, OFF),
        ),
        ReplCase(
            id="operational-lit-light-set-to-black-switches-off",
            paired=True,
            online=True,
            stored_light=GREEN_AT_TEN_PERCENT,
            inputs=(),
            typed=(OFF,),
            published=(BLACK_ATTRIBUTES, {"on": False}),
            pixel=(BOOT_WHITE, GREEN, OFF),
        ),
    ],
    ids=lambda case: case.id,
)
def test_scenario_set_color_at_repl(run_light, case):
    """Stop the loop after its first poll, as Ctrl-C does, then type colours at the REPL.

    set_color() writes no JSON lines, so only the published batches and the
    pixel are checked.
    """
    outcome = run_light(
        paired=case.paired,
        online=case.online,
        stored_light=case.stored_light,
        inputs=case.inputs,
        until_ms=0,
        typed=case.typed,
    )

    assert outcome.published == case.published
    assert outcome.pixel == case.pixel


@pytest.mark.parametrize(
    "board",
    [
        Board(
            id="esp32s3-drives-the-pixel-on-gpio21",
            machine="Generic ESP32S3 module with ESP32S3",
            error=None,
            pins=((21, machine.Pin.OUT),),
        ),
        Board(
            id="rp2040-raises-before-claiming-a-pin",
            machine="RP2040",
            error="unsupported board: RP2040",
            pins=(),
        ),
    ],
    ids=lambda board: board.id,
)
def test_scenario_board(run_light, board):
    """Only an ESP32-S3 boots; any other board stops before touching hardware."""
    raises = (
        contextlib.nullcontext()
        if board.error is None
        else pytest.raises(RuntimeError, match=board.error)
    )
    with raises:
        run_light(
            paired=False,
            online=False,
            stored_light=None,
            inputs=(),
            until_ms=0,
            machine_name=board.machine,
        )

    assert tuple(machine.pin_constructions) == board.pins
