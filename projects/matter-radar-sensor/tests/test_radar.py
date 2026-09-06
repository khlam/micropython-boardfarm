"""Radar supervision, recovery, filtering, and telemetry tests."""

import asyncio
from types import SimpleNamespace

import pytest

from micropython_stubs.testing import StopLoopError, json_lines


class FakeRadar:
    """Script reports, closure, and close errors for an already-detected radar."""

    def __init__(self, *, reports=(), close_error=None, model="LD2450") -> None:
        """Store the scripted outcomes."""
        self.reports = list(reports)
        self.close_error = close_error
        self.model = model
        self.close_calls = 0

    async def read_latest(self):
        """Return or raise the next scripted report outcome."""
        outcome = self.reports.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def close(self) -> None:
        """Record closure and raise its scripted failure."""
        self.close_calls += 1
        if self.close_error is not None:
            raise self.close_error


class FakeDetect:
    """Stand in for radar.detect(), returning or raising one outcome at a time."""

    def __init__(self, outcomes) -> None:
        """Store detection outcomes and arguments."""
        self.outcomes = list(outcomes)
        self.calls = []

    async def __call__(self, **kwargs) -> tuple:
        """Return the next detected (model, driver) pair, or raise its failure."""
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome.model, outcome


def test_run_starts_matter_dashboard_and_radar_tasks(load_application, monkeypatch):
    application = load_application().application
    calls = []

    async def matter_poll():
        calls.append("matter")

    async def dashboard():
        calls.append("dashboard")

    async def radar():
        calls.append("radar")

    monkeypatch.setattr(application, "_run_matter", matter_poll)
    monkeypatch.setattr(application, "_run_dashboard", dashboard)
    monkeypatch.setattr(application, "_run_radar", radar)

    asyncio.run(application.run())

    assert calls == ["matter", "dashboard", "radar"]


def test_radar_filters_targets_and_decimates_dashboard_reports(
    load_application, monkeypatch, capsys
):
    boot = load_application(commissioned=True)
    module = boot.module
    near = SimpleNamespace(slot=0, x_mm=3, y_mm=4, speed_cm_s=1, resolution_mm=10)
    far = SimpleNamespace(slot=1, x_mm=60, y_mm=80, speed_cm_s=2, resolution_mm=20)
    radar = FakeRadar(reports=[(near, far), (), (far,), StopLoopError()])
    factory = FakeDetect([radar])
    boot.time.script = [0, 499, 500]
    monkeypatch.setattr(module, "detect", factory)
    capsys.readouterr()

    with pytest.raises(StopLoopError):
        asyncio.run(boot.application._run_radar())

    lines = json_lines(capsys.readouterr().out)
    reports = [line for line in lines if "targets" in line]
    far_fields = {
        "slot": 1,
        "x_mm": 60,
        "y_mm": 80,
        "speed_cm_s": 2,
        "resolution_mm": 20,
    }
    assert factory.calls == [{"bus_id": 1, "tx": 5, "rx": 6}]
    assert [line.get("diag") for line in lines if "diag" in line] == ["radar_ok"]
    assert reports == [
        {"t": 0, "targets": [far_fields]},
        {"t": 500, "targets": [far_fields]},
    ]
    assert boot.application._occupancy_state == module._OCCUPIED
    assert boot.application._radar_healthy is True


def test_repeated_readiness_failures_report_once_until_recovery(
    load_application, monkeypatch, capsys
):
    boot = load_application()
    module = boot.module
    recovered = FakeRadar(reports=[StopLoopError()])
    # detect() owns probing, so both failures surface from it: an absent radar
    # and then a UART that failed while probing one.
    factory = FakeDetect([module.NoRadarError("absent"), OSError("uart init"), recovered])
    sleeps = []

    async def sleep_ms(delay_ms):
        sleeps.append(delay_ms)

    monkeypatch.setattr(module, "detect", factory)
    monkeypatch.setattr(asyncio, "sleep_ms", sleep_ms)
    capsys.readouterr()

    with pytest.raises(StopLoopError):
        asyncio.run(boot.application._run_radar())

    lines = json_lines(capsys.readouterr().out)
    assert [line.get("diag") for line in lines if "diag" in line] == ["no_device", "radar_ok"]
    assert lines[0]["err"] == "absent"
    assert sleeps == [module._RADAR_RETRY_MS, module._RADAR_RETRY_MS]
    assert factory.outcomes == []  # every failure re-detected from scratch
    assert boot.application._radar_healthy is True
    assert boot.application._occupancy_state == module._OCCUPIED


def test_read_error_and_timeout_recreate_radar_with_distinct_diagnostics(
    load_application, monkeypatch, capsys
):
    boot = load_application()
    module = boot.module
    read_error = FakeRadar(reports=[OSError("read failed")])
    timeout = FakeRadar(reports=[None])
    recovered = FakeRadar(reports=[StopLoopError()])
    factory = FakeDetect([read_error, timeout, recovered])
    sleeps = []

    async def sleep_ms(delay_ms):
        sleeps.append(delay_ms)

    boot.time.script = [321]
    monkeypatch.setattr(module, "detect", factory)
    monkeypatch.setattr(asyncio, "sleep_ms", sleep_ms)
    capsys.readouterr()

    with pytest.raises(StopLoopError):
        asyncio.run(boot.application._run_radar())

    lines = json_lines(capsys.readouterr().out)
    failures = [line for line in lines if line.get("diag") in {"read_err", "report_timeout"}]
    assert failures == [
        {"diag": "read_err", "err": "read failed"},
        {"diag": "report_timeout", "t": 321},
    ]
    assert sleeps == [module._RADAR_RETRY_MS, module._RADAR_RETRY_MS]
    assert read_error.close_calls == 1
    assert timeout.close_calls == 1
    assert boot.application._radar_healthy is True


def test_failure_forces_occupied_and_ignores_close_errors(load_application, capsys):
    boot = load_application(commissioned=True)
    application = boot.application
    application._apply_empty_report(now_ms=0)
    radar = FakeRadar(close_error=OSError("close failed"))
    capsys.readouterr()

    application._handle_radar_failure(radar, {"diag": "report_timeout", "t": 44})
    application._handle_radar_failure(radar, {"diag": "report_timeout", "t": 45})
    application._handle_radar_failure(None, {"diag": "read_err"})

    lines = json_lines(capsys.readouterr().out)
    assert [line for line in lines if line.get("diag") == "report_timeout"] == [
        {"diag": "report_timeout", "t": 44}
    ]
    assert radar.close_calls == 2
    assert application._occupancy_state == boot.module._OCCUPIED
    assert application._hold_started_ms is None
    assert application._radar_healthy is False
    assert application._pixel.writes[-1] == boot.module._RADAR_FAILED_COLOR
