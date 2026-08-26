"""Matter polling supervision and fail-safe occupancy tests."""

import asyncio

import _matter
import pytest

from matter.schema import Paths

_FABRIC = (1, 0x1234, 0x5678, 0xFFF1, "controller")


def test_poll_failure_forces_occupied_and_reports_once(
    load_application, monkeypatch, capsys, stop_task_error, json_lines
):
    boot = load_application(fabrics=(_FABRIC,))
    application = boot.application
    application._apply_empty_report(now_ms=1)
    _matter.inject_remote_write(application._hold_control.id, *Paths.ON_OFF, True)
    _matter.fail_next("snapshot")

    async def stop_sleep(_delay_ms):
        raise stop_task_error

    monkeypatch.setattr(boot.module.asyncio, "sleep_ms", stop_sleep)
    capsys.readouterr()

    with pytest.raises(stop_task_error):
        asyncio.run(application._run_matter())

    assert application._matter_healthy is False
    assert application._occupancy_state == boot.module._OCCUPIED
    assert application._pixel.writes[-1] == boot.module._RADAR_FAILED_COLOR
    assert json_lines(capsys.readouterr().out) == [
        {"diag": "matter_poll_err", "err": "[Errno 5] injected snapshot failure"}
    ]


def test_successful_poll_clears_failure_and_resumes_vacancy(
    load_application, monkeypatch, capsys, stop_task_error, json_lines
):
    boot = load_application()
    application = boot.application
    _matter.inject_remote_write(application._hold_control.id, *Paths.ON_OFF, True)
    _matter.fail_next("snapshot")
    sleeps = 0

    async def two_iterations(_delay_ms):
        nonlocal sleeps
        sleeps += 1
        if sleeps == 2:
            raise stop_task_error

    monkeypatch.setattr(boot.module.asyncio, "sleep_ms", two_iterations)
    capsys.readouterr()

    with pytest.raises(stop_task_error):
        asyncio.run(application._run_matter())

    assert application._matter_healthy is True
    assert json_lines(capsys.readouterr().out)[-1] == {"diag": "matter_ok"}
    application._hold_control.set(on=False)
    application._apply_radar_report(occupied=False, now_ms=10)
    assert application._occupancy_state == boot.module._VACANT
