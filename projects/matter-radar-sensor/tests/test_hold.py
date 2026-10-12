"""The occupancy hold: its README state diagram, and the hold light's mapping."""

from collections import namedtuple

import pytest

# MicroPython's tick counter wraps at 2**30 ms.
TICKS_PERIOD = 1 << 30

# Inputs to the hold state machine.
Report = namedtuple("Report", ("occupied", "now_ms", "hold_ms"))
Fault = namedtuple("Fault", ())

# ``given`` reaches the start state from boot (occupied); ``occupied`` is the
# state after each ``when`` input.
Case = namedtuple("Case", ("id", "given", "when", "occupied"))
Light = namedtuple("Light", ("id", "on", "level", "hold_ms"))


@pytest.mark.parametrize(
    "case",
    [
        Case(
            id="occupied-target-stays-occupied",
            given=(),
            when=(Report(occupied=True, now_ms=0, hold_ms=1_000),),
            occupied=(True,),
        ),
        Case(
            id="occupied-first-empty-report-starts-holding",
            given=(),
            when=(Report(occupied=False, now_ms=0, hold_ms=1_000),),
            occupied=(True,),
        ),
        Case(
            id="occupied-first-empty-report-with-zero-hold-vacates",
            given=(),
            when=(Report(occupied=False, now_ms=0, hold_ms=0),),
            occupied=(False,),
        ),
        Case(
            id="holding-empty-report-before-the-hold-passes-stays-holding",
            given=(Report(occupied=False, now_ms=100, hold_ms=1_000),),
            when=(Report(occupied=False, now_ms=1_099, hold_ms=1_000),),
            occupied=(True,),
        ),
        Case(
            id="holding-empty-report-when-the-hold-passes-vacates",
            given=(Report(occupied=False, now_ms=100, hold_ms=1_000),),
            when=(Report(occupied=False, now_ms=1_100, hold_ms=1_000),),
            occupied=(False,),
        ),
        Case(
            id="holding-target-reacquired-restarts-the-next-hold",
            given=(Report(occupied=False, now_ms=0, hold_ms=1_000),),
            when=(
                Report(occupied=True, now_ms=900, hold_ms=1_000),
                Report(occupied=False, now_ms=1_000, hold_ms=1_000),
                Report(occupied=False, now_ms=1_999, hold_ms=1_000),
            ),
            occupied=(True, True, True),
        ),
        Case(
            id="holding-fault-discards-the-hold",
            given=(Report(occupied=False, now_ms=0, hold_ms=1_000),),
            when=(Fault(), Report(occupied=False, now_ms=1_000, hold_ms=1_000)),
            occupied=(True, True),
        ),
        Case(
            id="holding-shortened-hold-measures-from-the-first-empty-report",
            given=(Report(occupied=False, now_ms=10, hold_ms=2_000),),
            when=(Report(occupied=False, now_ms=1_010, hold_ms=1_000),),
            occupied=(False,),
        ),
        Case(
            id="holding-lengthened-hold-measures-from-the-first-empty-report",
            given=(Report(occupied=False, now_ms=10, hold_ms=1_001),),
            when=(Report(occupied=False, now_ms=1_010, hold_ms=2_000),),
            occupied=(True,),
        ),
        Case(
            id="holding-hold-removed-vacates-on-the-next-empty-report",
            given=(Report(occupied=False, now_ms=10, hold_ms=1_001),),
            when=(Report(occupied=False, now_ms=1_010, hold_ms=0),),
            occupied=(False,),
        ),
        Case(
            id="holding-hold-measures-elapsed-time-across-the-tick-wrap",
            given=(Report(occupied=False, now_ms=TICKS_PERIOD - 1_000, hold_ms=2_000),),
            when=(
                Report(occupied=False, now_ms=999, hold_ms=2_000),
                Report(occupied=False, now_ms=1_000, hold_ms=2_000),
            ),
            occupied=(True, False),
        ),
        Case(
            id="vacant-empty-report-stays-vacant-even-with-a-longer-hold",
            given=(Report(occupied=False, now_ms=0, hold_ms=0),),
            when=(Report(occupied=False, now_ms=1, hold_ms=600_000),),
            occupied=(False,),
        ),
        Case(
            id="vacant-target-reacquired-occupies",
            given=(Report(occupied=False, now_ms=0, hold_ms=0),),
            when=(Report(occupied=True, now_ms=1, hold_ms=0),),
            occupied=(True,),
        ),
        Case(
            id="vacant-fault-occupies",
            given=(Report(occupied=False, now_ms=0, hold_ms=0),),
            when=(Fault(),),
            occupied=(True,),
        ),
    ],
    ids=lambda case: case.id,
)
def test_hold_follows_the_readme_state_diagram(hold, case):
    """Apply each report or fault and check whether the room still counts as occupied."""
    machine = hold.Hold()
    for step in case.given:
        _apply(machine, step)

    observed = []
    for step in case.when:
        _apply(machine, step)
        observed.append(machine.occupied)

    assert tuple(observed) == case.occupied


@pytest.mark.parametrize(
    "light",
    [
        Light(id="off-at-full-level-removes-the-hold", on=False, level=254, hold_ms=0),
        Light(id="on-at-level-0-is-no-hold", on=True, level=0, hold_ms=0),
        Light(id="on-at-half-level-is-five-minutes", on=True, level=127, hold_ms=300_000),
        Light(id="on-at-full-level-is-ten-minutes", on=True, level=254, hold_ms=600_000),
    ],
    ids=lambda light: light.id,
)
def test_hold_ms_maps_the_hold_light_to_zero_through_ten_minutes(hold, light):
    """The hold light's level maps linearly onto zero to ten minutes; off is zero."""
    assert hold.hold_ms(on=light.on, level=light.level) == light.hold_ms


def _apply(machine, step):
    """Feed one input value to the hold state machine."""
    if isinstance(step, Fault):
        machine.force_occupied()
    else:
        machine.report(occupied=step.occupied, now_ms=step.now_ms, hold_ms=step.hold_ms)


@pytest.fixture
def hold(firmware_module):
    """The firmware hold module, on the wrap-safe fake clock."""
    return firmware_module("hold")
