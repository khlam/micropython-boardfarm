"""Occupancy hold, dead zone, and telemetry pacing rules."""

from collections.abc import Callable
from types import ModuleType, SimpleNamespace

import pytest

_FIVE_MINUTES_MS = 300_000
_TEN_MINUTES_MS = 600_000
# An Occupancy step that forces occupied instead of applying a report.
_FORCE = None


@pytest.mark.parametrize(
    ("x_mm", "y_mm", "expected"),
    [(0, 0, False), (6, 7, False), (6, 8, True), (-10, 0, True)],
)
def test_dead_zone_boundary(reports: ModuleType, x_mm: int, y_mm: int, expected: bool):
    """Targets within the dead zone around the sensor don't count as outside it.

    Args:
        reports: The firmware reports module.
        x_mm: The target's lateral offset.
        y_mm: The target's range.
        expected: Whether the target lies outside the dead zone.
    """
    assert reports.outside_dead_zone(SimpleNamespace(x_mm=x_mm, y_mm=y_mm)) is expected


@pytest.mark.parametrize(
    ("on", "level", "expected"),
    [(False, 254, 0), (True, 0, 0), (True, 127, _FIVE_MINUTES_MS), (True, 254, _TEN_MINUTES_MS)],
)
def test_hold_control_maps_level_to_zero_through_ten_minutes(
    reports: ModuleType, on: bool, level: int, expected: int
):
    """The hold light's level maps linearly onto zero to ten minutes; off is zero.

    Args:
        reports: The firmware reports module.
        on: The hold light's on/off state.
        level: The hold light's level.
        expected: The hold in milliseconds.
    """
    assert reports.hold_ms(on=on, level=level) == expected


@pytest.mark.parametrize(
    "steps",
    [
        pytest.param([(False, 100, 0, False)], id="zero-hold-clears-on-the-first-empty-report"),
        pytest.param(
            [
                (False, 100, _FIVE_MINUTES_MS, True),
                (False, 100 + _FIVE_MINUTES_MS - 1, _FIVE_MINUTES_MS, True),
                (False, 100 + _FIVE_MINUTES_MS, _FIVE_MINUTES_MS, False),
            ],
            id="hold-is-anchored-to-the-first-empty-report",
        ),
        pytest.param(
            [
                (False, 10, _FIVE_MINUTES_MS + 1, True),
                (False, 10 + _FIVE_MINUTES_MS, _FIVE_MINUTES_MS, False),
            ],
            id="shortened-hold-measures-from-the-original-start",
        ),
        pytest.param(
            [
                (False, 10, _FIVE_MINUTES_MS + 1, True),
                (False, 10 + _FIVE_MINUTES_MS, _TEN_MINUTES_MS, True),
            ],
            id="lengthened-hold-measures-from-the-original-start",
        ),
        pytest.param(
            [(False, 10, _FIVE_MINUTES_MS + 1, True), (False, 10 + _FIVE_MINUTES_MS, 0, False)],
            id="hold-removed-mid-hold-clears",
        ),
        pytest.param(
            [
                (False, 0, 1_000, True),
                (True, 900, 1_000, True),
                (False, 1_000, 1_000, True),
                (False, 1_999, 1_000, True),
            ],
            id="target-during-hold-restarts-the-next-hold",
        ),
        pytest.param(
            [(False, 0, 1_000, True), (_FORCE, None, None, True), (False, 1_000, 1_000, True)],
            id="forcing-occupied-cancels-the-hold",
        ),
        pytest.param(
            [(False, 0, 0, False), (False, 1, _TEN_MINUTES_MS, False), (True, 2, 0, True)],
            id="vacancy-stays-until-a-target-returns",
        ),
        pytest.param(
            [(False, -1_000, 2_000, True), (False, 999, 2_000, True), (False, 1_000, 2_000, False)],
            id="hold-measures-elapsed-time-across-tick-wrap",
        ),
    ],
)
def test_occupancy_hold(
    reports: ModuleType, steps: list[tuple[bool | None, int | None, int | None, bool]]
):
    """Each step applies a report ``(occupied, now_ms, hold_ms)`` or forces occupied.

    Args:
        reports: The firmware reports module, running on the fake clock.
        steps: Each ends with whether occupancy holds afterwards. A negative
            ``now_ms`` sits that far before the tick counter wraps.
    """
    period = reports.time._PERIOD
    occupancy = reports.Occupancy()

    observed = []
    for occupied, now_ms, hold_ms, _expected in steps:
        if occupied is _FORCE:
            occupancy.force_occupied()
        else:
            occupancy.report(occupied=occupied, now_ms=now_ms % period, hold_ms=hold_ms)
        observed.append(occupancy.occupied)

    assert observed == [step[-1] for step in steps]


@pytest.mark.parametrize(
    "steps",
    [
        pytest.param(
            [
                (("far",), 0, True),
                (("moved",), 499, False),  # inside the interval
                (("far",), 500, False),  # interval passed, but unchanged
                (("moved",), 999, False),  # the unchanged report restarted the interval
                (("moved",), 1_000, True),
            ],
            id="changed-targets-at-most-once-per-interval",
        ),
        pytest.param(
            [(("far",), 0, True), ((), 500, True), ((), 1_000, False)],
            id="empty-scene-after-targets-is-sent-once",
        ),
        pytest.param(
            [(("far",), -100, True), (("moved",), 399, False), (("moved",), 400, True)],
            id="interval-survives-tick-wrap",
        ),
    ],
)
def test_report_throttle(reports: ModuleType, steps: list[tuple[tuple[str, ...], int, bool]]):
    """Each step offers ``(targets, now_ms)`` and ends with whether it is due.

    Args:
        reports: The firmware reports module, running on the fake clock.
        steps: The offers in order. A negative ``now_ms`` sits that far before
            the tick counter wraps.
    """
    period = reports.time._PERIOD
    throttle = reports.ReportThrottle()

    due = [throttle.due(targets, now_ms % period) for targets, now_ms, _expected in steps]

    assert due == [step[-1] for step in steps]


@pytest.fixture
def reports(firmware_module: Callable[[str], ModuleType]) -> ModuleType:
    """The firmware reports module, imported fresh.

    Args:
        firmware_module: Imports the module from the firmware directory.

    Returns:
        The reports module.
    """
    return firmware_module("reports")
