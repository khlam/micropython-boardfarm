"""Which radar targets count, and when their telemetry is sent."""

from collections import namedtuple

import pytest

from radar import Target

# MicroPython's tick counter wraps at 2**30 ms.
TICKS_PERIOD = 1 << 30

FAR = Target(slot=1, x_mm=60, y_mm=80, speed_cm_s=2, resolution_mm=20)
MOVED = Target(slot=1, x_mm=61, y_mm=80, speed_cm_s=2, resolution_mm=20)

DeadZone = namedtuple("DeadZone", ("id", "x_mm", "y_mm", "outside"))
# One offer of a report's targets to the throttle.
Offer = namedtuple("Offer", ("targets", "now_ms"))
# ``due`` says, for each offer in turn, whether to send it.
Pacing = namedtuple("Pacing", ("id", "offers", "due"))


@pytest.mark.parametrize(
    "zone",
    [
        DeadZone(id="at-the-sensor-is-inside", x_mm=0, y_mm=0, outside=False),
        DeadZone(id="9.2-mm-away-is-inside", x_mm=6, y_mm=7, outside=False),
        DeadZone(id="exactly-10-mm-away-is-outside", x_mm=6, y_mm=8, outside=True),
        DeadZone(id="10-mm-to-the-left-is-outside", x_mm=-10, y_mm=0, outside=True),
    ],
    ids=lambda zone: zone.id,
)
def test_outside_dead_zone_ignores_targets_within_10_mm(targets, zone):
    """Targets closer than 10 mm to the sensor do not count."""
    target = Target(slot=1, x_mm=zone.x_mm, y_mm=zone.y_mm, speed_cm_s=0, resolution_mm=0)

    assert targets.outside_dead_zone(target) is zone.outside


@pytest.mark.parametrize(
    "pacing",
    [
        Pacing(
            # The unchanged offer at 500 ms still restarts the interval.
            id="changed-targets-are-sent-at-most-once-per-500-ms",
            offers=(
                Offer(targets=(FAR,), now_ms=0),
                Offer(targets=(MOVED,), now_ms=499),
                Offer(targets=(FAR,), now_ms=500),
                Offer(targets=(MOVED,), now_ms=999),
                Offer(targets=(MOVED,), now_ms=1_000),
            ),
            due=(True, False, False, False, True),
        ),
        Pacing(
            id="room-empties-and-the-empty-scene-is-sent-once",
            offers=(
                Offer(targets=(FAR,), now_ms=0),
                Offer(targets=(), now_ms=500),
                Offer(targets=(), now_ms=1_000),
            ),
            due=(True, True, False),
        ),
        Pacing(
            id="interval-is-measured-across-the-tick-wrap",
            offers=(
                Offer(targets=(FAR,), now_ms=TICKS_PERIOD - 100),
                Offer(targets=(MOVED,), now_ms=399),
                Offer(targets=(MOVED,), now_ms=400),
            ),
            due=(True, False, True),
        ),
    ],
    ids=lambda pacing: pacing.id,
)
def test_target_throttle_sends_changed_targets_at_most_every_500_ms(targets, pacing):
    """The first offer is always due; later ones only when changed and 500 ms on."""
    throttle = targets.TargetThrottle()

    due = tuple(throttle.due(offer.targets, offer.now_ms) for offer in pacing.offers)

    assert due == pacing.due


@pytest.fixture
def targets(firmware_module):
    """The firmware targets module, on the wrap-safe fake clock."""
    return firmware_module("targets")
