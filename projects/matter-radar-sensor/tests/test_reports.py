"""Occupancy hold, dead zone, and telemetry pacing rules."""

from types import SimpleNamespace

import pytest

_FIVE_MINUTES_MS = 300_000
_TEN_MINUTES_MS = 600_000


@pytest.fixture
def reports(firmware_module):
    return firmware_module("reports")


@pytest.mark.parametrize(
    ("x_mm", "y_mm", "expected"),
    [(0, 0, False), (6, 7, False), (6, 8, True), (10, 0, True), (-10, 0, True)],
)
def test_dead_zone_boundary(reports, x_mm, y_mm, expected):
    assert reports.outside_dead_zone(SimpleNamespace(x_mm=x_mm, y_mm=y_mm)) is expected


@pytest.mark.parametrize(
    ("on", "level", "expected"),
    [(False, 254, 0), (True, 0, 0), (True, 127, _FIVE_MINUTES_MS), (True, 254, _TEN_MINUTES_MS)],
)
def test_hold_control_maps_level_to_zero_through_ten_minutes(reports, on, level, expected):
    assert reports.hold_ms(on=on, level=level) == expected


def test_zero_hold_clears_on_the_first_empty_report(reports):
    occupancy = reports.Occupancy()

    occupancy.report(occupied=False, now_ms=100, hold_ms=0)

    assert occupancy.occupied is False


def test_hold_is_anchored_to_the_first_empty_report(reports):
    occupancy = reports.Occupancy()

    occupancy.report(occupied=False, now_ms=100, hold_ms=_FIVE_MINUTES_MS)
    occupancy.report(occupied=False, now_ms=100 + _FIVE_MINUTES_MS - 1, hold_ms=_FIVE_MINUTES_MS)
    assert occupancy.occupied is True

    occupancy.report(occupied=False, now_ms=100 + _FIVE_MINUTES_MS, hold_ms=_FIVE_MINUTES_MS)
    assert occupancy.occupied is False


@pytest.mark.parametrize(
    ("new_hold_ms", "expected"),
    [(_FIVE_MINUTES_MS, False), (_TEN_MINUTES_MS, True), (0, False)],
)
def test_changing_the_hold_mid_hold_keeps_the_original_start(reports, new_hold_ms, expected):
    occupancy = reports.Occupancy()
    occupancy.report(occupied=False, now_ms=10, hold_ms=_TEN_MINUTES_MS // 2 + 1)

    occupancy.report(occupied=False, now_ms=10 + _FIVE_MINUTES_MS, hold_ms=new_hold_ms)

    assert occupancy.occupied is expected


def test_target_during_hold_restarts_the_next_hold(reports):
    occupancy = reports.Occupancy()
    occupancy.report(occupied=False, now_ms=0, hold_ms=1_000)

    occupancy.report(occupied=True, now_ms=900, hold_ms=1_000)
    occupancy.report(occupied=False, now_ms=1_000, hold_ms=1_000)
    occupancy.report(occupied=False, now_ms=1_999, hold_ms=1_000)

    assert occupancy.occupied is True


def test_forcing_occupied_cancels_the_hold(reports):
    occupancy = reports.Occupancy()
    occupancy.report(occupied=False, now_ms=0, hold_ms=1_000)

    occupancy.force_occupied()
    occupancy.report(occupied=False, now_ms=1_000, hold_ms=1_000)

    assert occupancy.occupied is True


def test_vacancy_stays_until_a_target_returns(reports):
    occupancy = reports.Occupancy()
    occupancy.report(occupied=False, now_ms=0, hold_ms=0)

    occupancy.report(occupied=False, now_ms=1, hold_ms=_TEN_MINUTES_MS)
    assert occupancy.occupied is False

    occupancy.report(occupied=True, now_ms=2, hold_ms=0)
    assert occupancy.occupied is True


def test_hold_measures_elapsed_time_across_tick_wrap(reports, firmware_module):
    period = firmware_module.time._PERIOD
    occupancy = reports.Occupancy()

    occupancy.report(occupied=False, now_ms=period - 1_000, hold_ms=2_000)
    occupancy.report(occupied=False, now_ms=999, hold_ms=2_000)
    assert occupancy.occupied is True

    occupancy.report(occupied=False, now_ms=1_000, hold_ms=2_000)
    assert occupancy.occupied is False


def test_throttle_sends_changed_targets_at_most_once_per_interval(reports):
    throttle = reports.ReportThrottle()
    first, moved = ("far",), ("moved",)

    assert [
        throttle.due(first, 0),
        throttle.due(moved, 499),  # inside the interval
        throttle.due(first, 500),  # interval passed, but unchanged
        throttle.due(moved, 999),  # the unchanged report restarted the interval
        throttle.due(moved, 1_000),
    ] == [True, False, False, False, True]


def test_throttle_sends_an_empty_scene_after_targets(reports):
    throttle = reports.ReportThrottle()
    throttle.due(("far",), 0)

    assert throttle.due((), 500) is True
    assert throttle.due((), 1_000) is False


def test_throttle_interval_survives_tick_wrap(reports, firmware_module):
    period = firmware_module.time._PERIOD
    throttle = reports.ReportThrottle()
    throttle.due(("far",), period - 100)

    assert throttle.due(("moved",), 399) is False
    assert throttle.due(("moved",), 400) is True
