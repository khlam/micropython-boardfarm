"""The README's contract, run through the real main() on the virtual bench.

Each row boots the firmware with a start state, delivers inputs at virtual
times, stops it at ``until_ms``, and lists everything that left it: the
occupancy values ESP-Matter accepted for endpoint 1 with their times, the
project's JSON lines, and every colour written to the pixel.

The radar reports on every 100 ms mark; Matter is polled on every 50 ms mark.
At one instant, inputs and the radar's report arrive before the firmware runs.
"""

from collections import namedtuple

import machine
import neopixel
import pytest
from radar_sensor_bench import (
    HoldLight,
    PairingFails,
    PollFault,
    PublishFault,
    Scene,
    Seen,
    Silent,
    StoredHoldLight,
    UartFault,
    WindowOpens,
)

# Targets the radar sees. PERSON is the README's telemetry example.
PERSON = Seen(x_mm=-782, y_mm=1713, speed_cm_s=-16, resolution_mm=320)
MOVED = Seen(x_mm=-700, y_mm=1713, speed_cm_s=-16, resolution_mm=320)
NEAR = Seen(x_mm=3, y_mm=4, speed_cm_s=1, resolution_mm=10)  # 5 mm away: inside the dead zone
RANGE_ONLY = Seen(x_mm=0, y_mm=1450, speed_cm_s=0, resolution_mm=0)  # all an LD2420 measures

# Telemetry entries for those targets.
PERSON_IN_SLOT_1 = {"slot": 1, "x_mm": -782, "y_mm": 1713, "speed_cm_s": -16, "resolution_mm": 320}
PERSON_IN_SLOT_2 = {**PERSON_IN_SLOT_1, "slot": 2}
MOVED_IN_SLOT_2 = {**PERSON_IN_SLOT_2, "x_mm": -700}
RANGE_IN_SLOT_1 = {"slot": 1, "x_mm": 0, "y_mm": 1450, "speed_cm_s": 0, "resolution_mm": 0}

# Diagnostic and error lines.
RADAR_OK = {"diag": "radar_ok", "model": "LD2450"}
NO_DEVICE = {"diag": "no_device", "err": "no supported radar answered"}
POLL_ERROR = {"diag": "matter_poll_err", "err": "[Errno 5] injected snapshot failure"}
MATTER_OK = {"diag": "matter_ok"}
PUBLISH_ERROR = {
    "event": "error",
    "component": "occupancy",
    "message": "[Errno 5] injected attributes_publish failure",
}

# Pixel colours at the status brightness of 8.
BOOT_WHITE = (8, 8, 8)
OCCUPIED_GREEN = (0, 8, 0)
VACANT_BLUE = (0, 0, 8)
UNHEALTHY_YELLOW = (8, 8, 0)
UNREACHABLE_AMBER = (8, 4, 0)
PAIRABLE_PURPLE = (8, 0, 8)
FAILED_RED = (8, 0, 0)
OFF = (0, 0, 0)

Case = namedtuple(
    "Case",
    (
        "id",
        # Start state.
        "paired",
        "online",
        "radar",
        "stored_hold_light",
        # Inputs.
        "inputs",
        "until_ms",
        # Outputs.
        "published",
        "lines",
        "pixel",
    ),
)

Board = namedtuple("Board", ("id", "machine", "error"))


@pytest.mark.parametrize(
    "case",
    [
        Case(
            id="paired-online-boot-publishes-occupied-then-shows-green",
            paired=True,
            online=True,
            radar="LD2450",
            stored_hold_light=None,
            inputs=(Scene(at_ms=0, targets=(PERSON,)),),
            until_ms=150,
            published=((0, 1),),
            lines=(RADAR_OK, {"t": 100, "targets": [PERSON_IN_SLOT_1]}),
            pixel=(BOOT_WHITE, OCCUPIED_GREEN),
        ),
        Case(
            id="occupied-empty-report-with-hold-light-off-publishes-vacant-at-once",
            paired=True,
            online=True,
            radar="LD2450",
            stored_hold_light=None,
            inputs=(Scene(at_ms=0, targets=()),),
            until_ms=150,
            published=((0, 1), (100, 0)),
            lines=(RADAR_OK, {"t": 100, "targets": []}),
            pixel=(BOOT_WHITE, OCCUPIED_GREEN, VACANT_BLUE),
        ),
        Case(
            id="vacant-target-enters-publishes-occupied-at-once",
            paired=True,
            online=True,
            radar="LD2450",
            stored_hold_light=None,
            inputs=(Scene(at_ms=0, targets=()), Scene(at_ms=1100, targets=(PERSON,))),
            until_ms=1150,
            published=((0, 1), (100, 0), (1100, 1)),
            lines=(
                RADAR_OK,
                {"t": 100, "targets": []},
                {"t": 1100, "targets": [PERSON_IN_SLOT_1]},
            ),
            pixel=(BOOT_WHITE, OCCUPIED_GREEN, VACANT_BLUE, OCCUPIED_GREEN),
        ),
        Case(
            id="vacant-target-inside-dead-zone-stays-vacant",
            paired=True,
            online=True,
            radar="LD2450",
            stored_hold_light=None,
            inputs=(Scene(at_ms=0, targets=(NEAR,)),),
            until_ms=150,
            published=((0, 1), (100, 0)),
            lines=(RADAR_OK, {"t": 100, "targets": []}),
            pixel=(BOOT_WHITE, OCCUPIED_GREEN, VACANT_BLUE),
        ),
        Case(
            # Level 1 of 254 is a 2362 ms hold; the room empties at 1000 ms.
            id="occupied-hold-light-at-level-1-holds-2362-ms-after-the-first-empty-report",
            paired=True,
            online=True,
            radar="LD2450",
            stored_hold_light=None,
            inputs=(
                HoldLight(at_ms=0, on=True, level=1),
                Scene(at_ms=0, targets=(PERSON,)),
                Scene(at_ms=1000, targets=()),
            ),
            until_ms=3450,
            published=((0, 1), (3400, 0)),
            lines=(
                RADAR_OK,
                {"t": 100, "targets": [PERSON_IN_SLOT_1]},
                {"t": 1100, "targets": []},
            ),
            pixel=(BOOT_WHITE, OCCUPIED_GREEN, VACANT_BLUE),
        ),
        Case(
            id="stored-hold-light-at-level-1-still-holds-after-a-reboot",
            paired=True,
            online=True,
            radar="LD2450",
            stored_hold_light=StoredHoldLight(on=True, level=1),
            inputs=(Scene(at_ms=0, targets=(PERSON,)), Scene(at_ms=1000, targets=())),
            until_ms=3450,
            published=((0, 1), (3400, 0)),
            lines=(
                RADAR_OK,
                {"t": 100, "targets": [PERSON_IN_SLOT_1]},
                {"t": 1100, "targets": []},
            ),
            pixel=(BOOT_WHITE, OCCUPIED_GREEN, VACANT_BLUE),
        ),
        Case(
            # A 4724 ms hold cut to 2362 ms at 2000 ms still ends 2362 ms after 1000 ms.
            id="holding-shortened-hold-measures-from-the-first-empty-report",
            paired=True,
            online=True,
            radar="LD2450",
            stored_hold_light=None,
            inputs=(
                HoldLight(at_ms=0, on=True, level=2),
                Scene(at_ms=0, targets=(PERSON,)),
                Scene(at_ms=1000, targets=()),
                HoldLight(at_ms=2000, on=True, level=1),
            ),
            until_ms=3450,
            published=((0, 1), (3400, 0)),
            lines=(
                RADAR_OK,
                {"t": 100, "targets": [PERSON_IN_SLOT_1]},
                {"t": 1100, "targets": []},
            ),
            pixel=(BOOT_WHITE, OCCUPIED_GREEN, VACANT_BLUE),
        ),
        Case(
            # Without the fault the hold would end at 3400 ms; the radar is back at 3100 ms.
            id="holding-radar-read-error-forces-occupied-and-restarts-the-hold",
            paired=True,
            online=True,
            radar="LD2450",
            stored_hold_light=None,
            inputs=(
                HoldLight(at_ms=0, on=True, level=1),
                Scene(at_ms=0, targets=(PERSON,)),
                Scene(at_ms=1000, targets=()),
                UartFault(at_ms=2050, message="read failed"),
            ),
            until_ms=5550,
            published=((0, 1), (5500, 0)),
            lines=(
                RADAR_OK,
                {"t": 100, "targets": [PERSON_IN_SLOT_1]},
                {"t": 1100, "targets": []},
                {"diag": "read_err", "err": "read failed"},
                RADAR_OK,
            ),
            pixel=(BOOT_WHITE, OCCUPIED_GREEN, UNHEALTHY_YELLOW, OCCUPIED_GREEN, VACANT_BLUE),
        ),
        Case(
            # The last report is at 1000 ms. Probes at 2500 ms fail silently; the
            # radar talks again at 5000 ms and the probe at 6000 ms finds it.
            id="vacant-radar-goes-silent-reports-one-timeout-and-is-found-again",
            paired=True,
            online=True,
            radar="LD2450",
            stored_hold_light=None,
            inputs=(
                Scene(at_ms=0, targets=()),
                Silent(at_ms=1050),
                Scene(at_ms=5000, targets=()),
            ),
            until_ms=6150,
            published=((0, 1), (100, 0), (1500, 1), (6100, 0)),
            lines=(
                RADAR_OK,
                {"t": 100, "targets": []},
                {"diag": "report_timeout", "t": 1500},
                RADAR_OK,
            ),
            pixel=(BOOT_WHITE, OCCUPIED_GREEN, VACANT_BLUE, UNHEALTHY_YELLOW, VACANT_BLUE),
        ),
        Case(
            # Each probe gives up after 2500 ms: 2000 ms for an LD2450, 500 ms for an LD2420.
            id="no-radar-reports-no-device-once-and-shows-yellow",
            paired=True,
            online=True,
            radar=None,
            stored_hold_light=None,
            inputs=(),
            until_ms=6050,
            published=((0, 1),),
            lines=(NO_DEVICE,),
            pixel=(BOOT_WHITE, OCCUPIED_GREEN, UNHEALTHY_YELLOW),
        ),
        Case(
            id="uart-fault-while-probing-reports-init-err-and-retries-after-a-second",
            paired=True,
            online=True,
            radar="LD2450",
            stored_hold_light=None,
            inputs=(
                UartFault(at_ms=0, message="uart init"),
                Scene(at_ms=0, targets=(PERSON,)),
            ),
            until_ms=1150,
            published=((0, 1),),
            lines=(
                {"diag": "init_err", "err": "uart init"},
                RADAR_OK,
                {"t": 1100, "targets": [PERSON_IN_SLOT_1]},
            ),
            pixel=(BOOT_WHITE, OCCUPIED_GREEN, UNHEALTHY_YELLOW, OCCUPIED_GREEN),
        ),
        Case(
            # Polls fail at 1050 and 1100 ms and succeed at 1150 ms. The radar
            # is never restarted, so radar_ok appears once.
            id="vacant-matter-poll-failures-force-occupied-report-once-and-recover",
            paired=True,
            online=True,
            radar="LD2450",
            stored_hold_light=None,
            inputs=(
                Scene(at_ms=0, targets=()),
                PollFault(at_ms=1010),
                PollFault(at_ms=1060),
            ),
            until_ms=1250,
            published=((0, 1), (100, 0), (1050, 1), (1200, 0)),
            lines=(RADAR_OK, {"t": 100, "targets": []}, POLL_ERROR, MATTER_OK),
            pixel=(
                BOOT_WHITE,
                OCCUPIED_GREEN,
                VACANT_BLUE,
                UNHEALTHY_YELLOW,
                OCCUPIED_GREEN,
                VACANT_BLUE,
            ),
        ),
        Case(
            id="occupied-failed-vacant-publish-is-retried-on-the-next-report",
            paired=True,
            online=True,
            radar="LD2450",
            stored_hold_light=None,
            inputs=(
                Scene(at_ms=0, targets=(PERSON,)),
                PublishFault(at_ms=950),
                Scene(at_ms=1000, targets=()),
            ),
            until_ms=1150,
            published=((0, 1), (1100, 0)),
            lines=(
                RADAR_OK,
                {"t": 100, "targets": [PERSON_IN_SLOT_1]},
                PUBLISH_ERROR,
                {"t": 1100, "targets": []},
            ),
            pixel=(BOOT_WHITE, OCCUPIED_GREEN, VACANT_BLUE),
        ),
        Case(
            id="occupied-failed-vacant-publish-then-target-returns-never-publishes-vacant",
            paired=True,
            online=True,
            radar="LD2450",
            stored_hold_light=None,
            inputs=(
                Scene(at_ms=0, targets=(PERSON,)),
                PublishFault(at_ms=950),
                Scene(at_ms=1000, targets=()),
                Scene(at_ms=1050, targets=(PERSON,)),
            ),
            until_ms=1150,
            published=((0, 1), (1100, 1)),
            lines=(RADAR_OK, {"t": 100, "targets": [PERSON_IN_SLOT_1]}, PUBLISH_ERROR),
            pixel=(BOOT_WHITE, OCCUPIED_GREEN, VACANT_BLUE, OCCUPIED_GREEN),
        ),
        Case(
            # The move at 300 ms waits for 600 ms; the unchanged scene at 1100 ms is not sent.
            id="occupied-moving-target-telemetry-sends-changes-at-most-every-500-ms",
            paired=True,
            online=True,
            radar="LD2450",
            stored_hold_light=None,
            inputs=(
                Scene(at_ms=0, targets=(NEAR, PERSON)),
                Scene(at_ms=300, targets=(NEAR, MOVED)),
            ),
            until_ms=1150,
            published=((0, 1),),
            lines=(
                RADAR_OK,
                {"t": 100, "targets": [PERSON_IN_SLOT_2]},
                {"t": 600, "targets": [MOVED_IN_SLOT_2]},
            ),
            pixel=(BOOT_WHITE, OCCUPIED_GREEN),
        ),
        Case(
            # The LD2450 probe gives up at 2000 ms; the LD2420 then answers.
            id="ld2420-is-found-after-the-ld2450-probe-and-reports-its-range",
            paired=True,
            online=True,
            radar="LD2420",
            stored_hold_light=None,
            inputs=(Scene(at_ms=0, targets=(RANGE_ONLY,)),),
            until_ms=2150,
            published=((0, 1),),
            lines=(
                {"diag": "radar_ok", "model": "LD2420"},
                {"t": 2100, "targets": [RANGE_IN_SLOT_1]},
            ),
            pixel=(BOOT_WHITE, OCCUPIED_GREEN),
        ),
        Case(
            id="unpaired-without-window-shows-amber-over-occupancy",
            paired=False,
            online=False,
            radar="LD2450",
            stored_hold_light=None,
            inputs=(Scene(at_ms=0, targets=()),),
            until_ms=150,
            published=((0, 1), (100, 0)),
            lines=(RADAR_OK, {"t": 100, "targets": []}),
            pixel=(BOOT_WHITE, UNREACHABLE_AMBER),
        ),
        Case(
            # The poll at 1050 ms sees the failure: 200 ms on, 200 ms off, three times.
            id="paired-failed-pairing-flashes-red-three-times-then-shows-green",
            paired=True,
            online=True,
            radar="LD2450",
            stored_hold_light=None,
            inputs=(Scene(at_ms=0, targets=(PERSON,)), PairingFails(at_ms=1010)),
            until_ms=2300,
            published=((0, 1),),
            lines=(RADAR_OK, {"t": 100, "targets": [PERSON_IN_SLOT_1]}),
            pixel=(
                BOOT_WHITE,
                OCCUPIED_GREEN,
                FAILED_RED,
                OFF,
                FAILED_RED,
                OFF,
                FAILED_RED,
                OFF,
                OCCUPIED_GREEN,
            ),
        ),
        Case(
            # Purple blinks 500 ms on, 500 ms off while the window is open.
            id="unpaired-no-radar-still-opens-pairing-and-blinks-purple",
            paired=False,
            online=False,
            radar=None,
            stored_hold_light=None,
            inputs=(WindowOpens(at_ms=0),),
            until_ms=2600,
            published=((0, 1),),
            lines=(NO_DEVICE,),
            pixel=(BOOT_WHITE, PAIRABLE_PURPLE, OFF, PAIRABLE_PURPLE, OFF, PAIRABLE_PURPLE, OFF),
        ),
    ],
    ids=lambda case: case.id,
)
def test_scenario_readme_contract(run_scenario, case):
    """Run one README contract line through main() and check everything that left it."""
    outcome = run_scenario(
        paired=case.paired,
        online=case.online,
        radar=case.radar,
        stored_hold_light=case.stored_hold_light,
        inputs=case.inputs,
        until_ms=case.until_ms,
    )

    assert outcome.published == case.published
    assert outcome.lines == case.lines
    assert outcome.pixel == case.pixel


@pytest.mark.parametrize(
    "board",
    [
        Board(
            id="rp2040-raises-before-claiming-a-pin",
            machine="RP2040",
            error="unsupported board: RP2040",
        ),
    ],
    ids=lambda board: board.id,
)
def test_scenario_unsupported_board(load_firmware, board):
    """Only an ESP32-S3 boots; any other board stops before touching hardware."""
    with pytest.raises(RuntimeError, match=board.error):
        load_firmware(machine_name=board.machine)

    assert machine.pin_constructions == []
    assert neopixel.NeoPixel.instances == []
