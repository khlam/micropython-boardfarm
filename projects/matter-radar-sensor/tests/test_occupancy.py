"""Occupancy publication through Matter and the hold control endpoint."""

import _matter


def test_hold_control_endpoint_sets_the_hold(load_application):
    boot = load_application(commissioned=True)
    application = boot.application
    application._hold_control.set(on=True, level=127)

    application._apply_radar_report(occupied=False, now_ms=100)
    application._apply_radar_report(occupied=False, now_ms=300_099)
    assert application._occupancy.occupancy == 1
    assert application._status._pixel.writes[-1] == boot.status_module._OCCUPIED_COLOR

    application._apply_radar_report(occupied=False, now_ms=300_100)
    assert application._occupancy.occupancy == 0
    assert application._status._pixel.writes[-1] == boot.status_module._VACANT_COLOR


def test_failed_matter_polling_holds_occupied_through_empty_reports(load_application):
    application = load_application().application
    application._matter_healthy = False

    application._apply_radar_report(occupied=False, now_ms=100)

    assert application._occupancy.occupancy == 1


def test_publication_failure_is_retried_on_the_next_report(load_application, capsys):
    application = load_application().application
    capsys.readouterr()
    _matter.fail_next("attributes_publish")

    application._apply_radar_report(occupied=False, now_ms=1)

    assert application._published_occupancy is None
    assert '"component": "occupancy"' in capsys.readouterr().out

    application._apply_radar_report(occupied=False, now_ms=2)

    assert application._published_occupancy is False
    assert application._occupancy.occupancy == 0


def test_target_after_failed_clear_republishes_occupied(load_application):
    application = load_application().application
    _matter.fail_next("attributes_publish")
    application._apply_radar_report(occupied=False, now_ms=1)

    application._apply_radar_report(occupied=True, now_ms=2)

    assert application._occupancy.occupancy == 1
    assert application._published_occupancy is True
