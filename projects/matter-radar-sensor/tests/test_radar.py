"""Radar supervision, recovery, filtering, and telemetry tests."""

import asyncio
from collections.abc import Callable, Iterable
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

    def __init__(
        self,
        *,
        reports: Iterable[tuple | Exception | None] = (),
        close_error: Exception | None = None,
        model: str = "LD2450",
    ) -> None:
        """Store the scripted outcomes.

        Args:
            reports: What each read_latest() call returns or raises, in order.
            close_error: What close() raises, or None to close cleanly.
            model: The model name detection reports.
        """
        self.reports = list(reports)
        self.close_error = close_error
        self.model = model
        self.close_calls = 0

    async def read_latest(self) -> tuple | None:
        """Return or raise the next scripted report outcome.

        Returns:
            The next scripted targets, or None for a report timeout.

        Raises:
            outcome: The next scripted outcome, when it is an exception.
        """
        outcome = self.reports.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def close(self) -> None:
        """Record closure and raise its scripted failure.

        Raises:
            self.close_error: The scripted close error, when there is one.
        """
        self.close_calls += 1
        if self.close_error is not None:
            raise self.close_error


class FakeDetect:
    """Stand in for radar.detect(), returning or raising one outcome at a time."""

    def __init__(self, outcomes: Iterable[FakeRadar | Exception]) -> None:
        """Store detection outcomes and arguments.

        Args:
            outcomes: The radar each call detects, or the exception it raises, in order.
        """
        self.outcomes = list(outcomes)
        self.calls = []

    async def __call__(self, **kwargs: int) -> tuple:
        """Return the next detected (model, driver) pair, or raise its failure.

        Args:
            **kwargs: The bus arguments, recorded for the test to check.

        Returns:
            The detected radar's model name and the radar itself.

        Raises:
            outcome: The next scripted outcome, when it is an exception.
        """
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome.model, outcome


@pytest.mark.parametrize(
    ("detections", "ticks", "lines", "closes", "occupancy"),
    [
        pytest.param(
            # 499 ms is inside the interval; 500 ms clears it but repeats the targets.
            [{"reports": [(_NEAR, _FAR), (), (_FAR,), (_MOVED,), StopLoopError()]}],
            [0, 499, 500, 1000],
            [_READY, {"t": 0, "targets": [_FAR_FIELDS]}, {"t": 1000, "targets": [_MOVED_FIELDS]}],
            [0],
            1,
            id="filters-the-dead-zone-and-paces-telemetry",
        ),
        pytest.param(
            # The repeated scene and the empty report 100 ms later are both withheld
            # from telemetry, but the empty report still empties the room.
            [{"reports": [(_FAR,), (_FAR,), (), StopLoopError()]}],
            [0, 600, 700],
            [_READY, {"t": 0, "targets": [_FAR_FIELDS]}],
            [0],
            0,
            id="occupancy-uses-reports-telemetry-skips",
        ),
        pytest.param(
            # detect() owns probing, so both failures surface from it: an absent radar
            # and then a UART that failed while probing one.
            [NoRadarError("absent"), OSError("uart init"), {"reports": [StopLoopError()]}],
            [],
            [{"diag": "no_device", "err": "absent"}, _READY],
            [0],
            1,
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
            1,
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
            1,
            id="failure-forces-occupied-and-ignores-close-errors",
        ),
    ],
)
def test_run_radar(
    load_application: Callable[..., SimpleNamespace],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    detections: list[dict[str, object] | Exception],
    ticks: list[int],
    lines: list[dict[str, object]],
    closes: list[int],
    occupancy: int,
):
    """Drive the radar task of a vacant, commissioned sensor through scripted detections.

    Every failure waits one retry period and re-detects on the board's pins.

    Args:
        load_application: Boots the firmware application.
        monkeypatch: Swaps in the fake detect() and a recording sleep.
        capsys: Captures the telemetry and diagnostic lines.
        detections: A dict detects a radar with those FakeRadar keyword
            arguments; an exception is what detection raises.
        ticks: Scripted clock readings, one per report.
        lines: Every JSON line the task emits, in order.
        closes: How often each detected radar was closed.
        occupancy: The published occupancy afterwards.
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
    assert application._occupancy.occupancy == occupancy
