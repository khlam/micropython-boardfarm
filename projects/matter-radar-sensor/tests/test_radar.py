"""Radar supervision, recovery, filtering, and telemetry tests."""

import asyncio
from types import SimpleNamespace

import pytest

from micropython_stubs.testing import StopLoopError, json_lines
from radar import NoRadarError

# A target outside the dead zone, then the same target one millimetre along.
# Each dict is also the telemetry the firmware is expected to emit for it.
_FAR_FIELDS = {"slot": 1, "x_mm": 60, "y_mm": 80, "speed_cm_s": 2, "resolution_mm": 20}
_MOVED_FIELDS = {**_FAR_FIELDS, "x_mm": 61}
_NEAR = SimpleNamespace(slot=0, x_mm=3, y_mm=4, speed_cm_s=1, resolution_mm=10)
_FAR = SimpleNamespace(**_FAR_FIELDS)
_MOVED = SimpleNamespace(**_MOVED_FIELDS)
_READY = {"diag": "radar_ok", "model": "LD2450"}


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


@pytest.mark.parametrize(
    ("detections", "ticks", "lines", "closes", "product"),
    [
        pytest.param(
            # 499 ms is inside the interval; 500 ms clears it but repeats the targets.
            [{"reports": [(_NEAR, _FAR), (), (_FAR,), (_MOVED,), StopLoopError()]}],
            [0, 499, 500, 1000],
            [_READY, {"t": 0, "targets": [_FAR_FIELDS]}, {"t": 1000, "targets": [_MOVED_FIELDS]}],
            [0],
            (1, "_OCCUPIED_COLOR"),
            id="filters-the-dead-zone-and-paces-telemetry",
        ),
        pytest.param(
            # The repeated scene and the empty report 100 ms later are both withheld
            # from telemetry, but the empty report still empties the room.
            [{"reports": [(_FAR,), (_FAR,), (), StopLoopError()]}],
            [0, 600, 700],
            [_READY, {"t": 0, "targets": [_FAR_FIELDS]}],
            [0],
            (0, "_VACANT_COLOR"),
            id="occupancy-uses-reports-telemetry-skips",
        ),
        pytest.param(
            # detect() owns probing, so both failures surface from it: an absent radar
            # and then a UART that failed while probing one.
            [NoRadarError("absent"), OSError("uart init"), {"reports": [StopLoopError()]}],
            [],
            [{"diag": "no_device", "err": "absent"}, _READY],
            [0],
            (1, "_OCCUPIED_COLOR"),
            id="repeated-detection-failures-reported-once-until-recovery",
        ),
        pytest.param(
            [
                {"reports": [OSError("read failed")]},
                {"reports": [None]},
                {"reports": [StopLoopError()]},
            ],
            [321],
            [
                _READY,
                {"diag": "read_err", "err": "read failed"},
                _READY,
                {"diag": "report_timeout", "t": 321},
                _READY,
            ],
            [1, 1, 0],
            (1, "_OCCUPIED_COLOR"),
            id="read-error-and-timeout-each-recreate-the-radar",
        ),
        pytest.param(
            [
                {"reports": [OSError("read failed")], "close_error": OSError("close failed")},
                StopLoopError(),
            ],
            [],
            [_READY, {"diag": "read_err", "err": "read failed"}],
            [1],
            (1, "_RADAR_FAILED_COLOR"),
            id="failure-forces-occupied-and-ignores-close-errors",
        ),
    ],
)
def test_run_radar(
    load_application, monkeypatch, capsys, detections, ticks, lines, closes, product
):
    """Drive the radar task of a vacant, commissioned sensor through scripted detections.

    A dict detects a radar with those keyword arguments; an exception is what
    detection raises. ``ticks`` scripts report times, and ``closes`` counts how
    often each detected radar was closed. ``product`` is the published occupancy
    and the status pixel's color afterwards. Every failure waits one retry
    period and re-detects on the board's pins.
    """
    boot = load_application(commissioned=True)
    module = boot.module
    application = boot.application
    application._apply_radar_report(occupied=False, now_ms=0)
    radars = [FakeRadar(**outcome) for outcome in detections if isinstance(outcome, dict)]
    remaining = iter(radars)
    detect = FakeDetect(
        [outcome if isinstance(outcome, Exception) else next(remaining) for outcome in detections]
    )
    sleeps = []

    async def sleep_ms(delay_ms):
        sleeps.append(delay_ms)

    boot.time.script = list(ticks)
    monkeypatch.setattr(module, "detect", detect)
    monkeypatch.setattr(asyncio, "sleep_ms", sleep_ms)
    capsys.readouterr()

    with pytest.raises(StopLoopError):
        asyncio.run(application._run_radar())

    assert json_lines(capsys.readouterr().out) == lines
    assert [radar.close_calls for radar in radars] == closes
    assert detect.calls == [{"bus_id": 1, "tx": 5, "rx": 6}] * len(detections)
    assert sleeps == [module._RADAR_RETRY_MS] * (len(detections) - 1)
    occupancy, color = product
    assert application._occupancy.occupancy == occupancy
    assert application._status._pixel.writes[-1] == getattr(boot.status_module, color)
