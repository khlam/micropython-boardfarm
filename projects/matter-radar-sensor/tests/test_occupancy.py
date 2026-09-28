"""Occupancy publication through Matter and the hold control endpoint."""

from collections.abc import Callable
from types import SimpleNamespace

import matter_native
import pytest

from matter.schema import Paths
from micropython_stubs.testing import json_lines

_PUBLISH_ERROR = {
    "event": "error",
    "component": "occupancy",
    "message": "[Errno 5] injected attributes_publish failure",
}


def test_hold_control_endpoint_sets_the_hold(load_application: Callable[..., SimpleNamespace]):
    """The hold light's level sets how long occupancy is held after the radar clears.

    Args:
        load_application: Boots the firmware application.
    """
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


@pytest.mark.parametrize(
    ("occupied", "published"),
    [
        pytest.param(False, 0, id="vacancy-retried"),
        pytest.param(True, 1, id="occupancy-republished-over-the-failed-clear"),
    ],
)
def test_failed_publication_is_retried_on_the_next_report(
    load_application: Callable[..., SimpleNamespace],
    capsys: pytest.CaptureFixture[str],
    occupied: bool,
    published: int,
):
    """A failed clear leaves Matter occupied until the next report publishes its state.

    Args:
        load_application: Boots the firmware application.
        capsys: Captures the error line the failed publish emits.
        occupied: What the radar reports after the failed clear.
        published: The occupancy Matter holds after that report.
    """
    application = load_application().application
    endpoint = application._occupancy
    matter_native.fail_next("attributes_publish")
    capsys.readouterr()

    application._apply_radar_report(occupied=False, now_ms=1)
    after_failure = matter_native.attribute_get(endpoint.id, *Paths.OCCUPANCY)
    application._apply_radar_report(occupied=occupied, now_ms=2)

    assert json_lines(capsys.readouterr().out) == [_PUBLISH_ERROR]
    assert after_failure == 1
    assert (endpoint.occupancy, matter_native.attribute_get(endpoint.id, *Paths.OCCUPANCY)) == (
        published,
        published,
    )
