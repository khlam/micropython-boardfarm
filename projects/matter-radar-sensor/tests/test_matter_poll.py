"""Matter polling supervision, fail-safe occupancy, and commissioning status."""

import asyncio
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import matter_native
import pytest

from matter.schema import Paths
from micropython_stubs.testing import StopLoopError, json_lines

_POLL_ERROR = {"diag": "matter_poll_err", "err": "[Errno 5] injected snapshot failure"}
_WINDOW_OPENED = 3


def _poll_fails(application: Any):
    """Fail the next poll: a controller write makes it fetch a snapshot, which fails.

    Args:
        application: The firmware application whose hold light is written.
    """
    matter_native.inject_remote_write(application._hold_control.id, *Paths.ON_OFF, False)
    matter_native.fail_next("snapshot")


def _poll_succeeds(_application: Any):
    """Leave the next poll with nothing to fail.

    Args:
        _application: The firmware application, left untouched.
    """


def _window_opens(_application: Any):
    """Open a commissioning window before the next poll.

    Args:
        _application: The firmware application, left untouched.
    """
    matter_native.inject_commissioning_event(_WINDOW_OPENED)


@pytest.mark.parametrize(
    ("polls", "diags", "color", "occupancy"),
    [
        pytest.param(
            [_poll_fails, _poll_fails],
            [_POLL_ERROR],
            "_RADAR_FAILED_COLOR",
            (1, 1),
            id="failure-reported-once-and-holds-occupied",
        ),
        pytest.param(
            [_poll_fails, _poll_succeeds],
            [_POLL_ERROR, {"diag": "matter_ok"}],
            "_OCCUPIED_COLOR",
            (1, 0),
            id="recovery-reported-and-vacancy-resumes",
        ),
        pytest.param(
            [_window_opens],
            [],
            "_COMMISSIONING_WINDOW_COLOR",
            (0, 0),
            id="commissioning-event-reaches-the-status-pixel",
        ),
    ],
)
def test_matter_poll(
    load_application: Callable[..., SimpleNamespace],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    polls: list[Callable[[Any], None]],
    diags: list[dict[str, str]],
    color: str,
    occupancy: tuple[int, int],
):
    """Each entry in ``polls`` stages one loop iteration of a vacant, commissioned sensor.

    Args:
        load_application: Boots the firmware application.
        monkeypatch: Replaces the loop's sleep with the next staged poll.
        capsys: Captures the diagnostic lines the loop emits.
        polls: One staging step per loop iteration.
        diags: The diagnostic lines the loop emits, in order.
        color: Name of the status constant the pixel shows after the loop.
        occupancy: The published value after the loop, then after one more empty
            radar report.
    """
    boot = load_application(commissioned=True)
    application = boot.application
    application._apply_radar_report(occupied=False, now_ms=0)
    pending = list(polls)

    async def stage_next_poll(_delay_ms):
        if not pending:
            raise StopLoopError
        pending.pop(0)(application)

    monkeypatch.setattr(asyncio, "sleep_ms", stage_next_poll)
    pending.pop(0)(application)
    capsys.readouterr()

    with pytest.raises(StopLoopError):
        asyncio.run(application._run_matter())
    pixel = application._status._pixel.writes[-1]
    published = [application._occupancy.occupancy]
    application._apply_radar_report(occupied=False, now_ms=1)
    published.append(application._occupancy.occupancy)

    assert [line for line in json_lines(capsys.readouterr().out) if "diag" in line] == diags
    assert pixel == getattr(boot.status_module, color)
    assert tuple(published) == occupancy
