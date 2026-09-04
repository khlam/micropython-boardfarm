"""Occupancy policy, hold control, and Matter publication tests."""

from types import SimpleNamespace

import _matter
import pytest

_FABRIC = (1, 0x1234, 0x5678, 0xFFF1, "controller")


def test_zero_hold_clears_on_the_first_empty_report(load_application):
    boot = load_application(fabrics=(_FABRIC,))

    boot.application._apply_radar_report(occupied=False, now_ms=100)

    assert boot.application._occupancy_state == boot.module._VACANT
    assert boot.application._hold_started_ms is None
    assert boot.application._occupancy.occupancy == 0
    assert boot.application._pixel.writes[-1] == boot.module._VACANT_COLOR


def test_hold_is_anchored_to_the_first_empty_report(load_application):
    boot = load_application()
    application = boot.application
    application._hold_control.set(on=True, level=127)

    application._apply_empty_report(now_ms=100)
    application._apply_empty_report(now_ms=300_099)

    assert application._occupancy_state == boot.module._EMPTY_HOLD
    assert application._hold_started_ms == 100
    assert application._occupancy.occupancy == 1

    application._apply_empty_report(now_ms=300_100)

    assert application._occupancy_state == boot.module._VACANT
    assert application._occupancy.occupancy == 0


def test_live_hold_shortening_applies_to_original_start(load_application):
    boot = load_application()
    application = boot.application
    application._hold_control.set(on=True, level=254)
    application._apply_empty_report(now_ms=10)

    application._hold_control.set(level=127)
    application._apply_empty_report(now_ms=300_010)

    assert application._occupancy_state == boot.module._VACANT


def test_live_hold_extension_pushes_deadline_out(load_application):
    boot = load_application()
    application = boot.application
    application._hold_control.set(on=True, level=127)
    application._apply_empty_report(now_ms=10)

    application._hold_control.set(level=254)
    application._apply_empty_report(now_ms=300_010)

    assert application._occupancy_state == boot.module._EMPTY_HOLD
    assert application._hold_started_ms == 10


def test_turning_hold_off_clears_on_next_empty_report(load_application):
    boot = load_application()
    application = boot.application
    application._hold_control.set(on=True, level=254)
    application._apply_empty_report(now_ms=25)

    application._hold_control.set(on=False)
    application._apply_empty_report(now_ms=26)

    assert application._occupancy_state == boot.module._VACANT


def test_reacquiring_target_cancels_pending_clear(load_application):
    boot = load_application()
    application = boot.application
    application._hold_control.set(on=True, level=254)
    application._apply_empty_report(now_ms=100)

    application._apply_radar_report(occupied=True, now_ms=200)

    assert application._occupancy_state == boot.module._OCCUPIED
    assert application._hold_started_ms is None
    assert application._occupancy.occupancy == 1


def test_hold_uses_wrap_safe_tick_difference(load_application):
    boot = load_application()
    application = boot.application
    period = boot.time._PERIOD
    application._hold_control.set(on=True, level=1)

    application._apply_empty_report(now_ms=period - 1_000)
    application._apply_empty_report(now_ms=1_500)

    assert boot.time.diff_calls[-1] == (1_500, period - 1_000)
    assert application._occupancy_state == boot.module._VACANT


def test_publication_failure_stays_pending_until_next_report(load_application, capsys):
    boot = load_application()
    application = boot.application
    capsys.readouterr()
    _matter.fail_next("attributes_publish")

    application._apply_empty_report(now_ms=1)

    assert application._occupancy_state == boot.module._VACANT
    assert application._occupancy.occupancy == 0
    assert application._published_occupancy is None
    assert '"component": "occupancy"' in capsys.readouterr().out

    application._apply_empty_report(now_ms=2)

    assert application._published_occupancy is False
    assert application._occupancy.occupancy == 0


def test_target_after_failed_clear_forces_native_value_back_to_occupied(load_application, capsys):
    boot = load_application()
    application = boot.application
    capsys.readouterr()
    _matter.fail_next("attributes_publish")
    application._apply_empty_report(now_ms=1)

    application._set_occupied()

    assert application._occupancy_state == boot.module._OCCUPIED
    assert application._occupancy.occupancy == 1
    assert application._published_occupancy is True


@pytest.mark.parametrize(
    ("x_mm", "y_mm", "expected"),
    [(0, 0, False), (6, 7, False), (6, 8, True), (10, 0, True), (-10, 0, True)],
)
def test_dead_zone_boundary(load_application, x_mm, y_mm, expected):
    application = load_application().application
    target = SimpleNamespace(x_mm=x_mm, y_mm=y_mm)

    assert application._outside_dead_zone(target) is expected
