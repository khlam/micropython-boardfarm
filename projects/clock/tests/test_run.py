"""Host CPython tests for the clock project firmware.

Covers emit(), run() idle loop, and main() init-retry paths. The loops are
infinite; tests escape them with a countdown ``time`` whose ``sleep_ms``
raises a BaseException after a set number of calls (run()/main() only catch
``Exception``).
"""

from __future__ import annotations

import json

import pytest


class _StopLoop(BaseException):
    """Sentinel that escapes the run()/main() `except Exception` guards."""


class _CountdownTime:
    """time stub whose sleep_ms raises _StopLoop after `stop_after` calls."""

    def __init__(self, stop_after: int) -> None:
        self.t = 0
        self._stop = stop_after
        self._sleeps = 0

    def ticks_ms(self) -> int:
        self.t += 1
        return self.t

    def ticks_diff(self, a: int, b: int) -> int:
        return a - b

    def sleep_ms(self, _ms: int) -> None:
        self._sleeps += 1
        if self._sleeps >= self._stop:
            raise _StopLoop


class _FakeDisplay:
    """Display stand-in recording show_lines and reassert calls."""

    def __init__(self) -> None:
        self.shown: list[tuple[str, str]] = []
        self.reasserts = 0

    def show_lines(self, top: str, bottom: str) -> None:
        self.shown.append((top, bottom))

    def reassert(self) -> None:
        self.reasserts += 1


# ---------------------------------------------------------------------------
# emit
# ---------------------------------------------------------------------------


def test_emit_writes_one_json_line(main_ns: object, capsys: pytest.CaptureFixture) -> None:
    main_ns.ns["emit"]({"fix": True, "day": "MONDAY"})
    out = capsys.readouterr().out.strip()
    assert json.loads(out) == {"fix": True, "day": "MONDAY"}


# ---------------------------------------------------------------------------
# run loop
# ---------------------------------------------------------------------------


def test_run_enters_streaming_state(main_ns: object) -> None:
    main_ns.ns["time"] = _CountdownTime(stop_after=1)

    with pytest.raises(_StopLoop):
        main_ns.ns["run"](_FakeDisplay())

    assert "streaming" in main_ns.status.calls


# ---------------------------------------------------------------------------
# main entry point
# ---------------------------------------------------------------------------


def test_main_reports_init_error_and_retries(main_ns: object) -> None:
    main_ns.ns["time"] = _CountdownTime(stop_after=2)
    emitted: list[dict] = []
    main_ns.ns["emit"] = lambda obj: emitted.append(dict(obj))

    def _boom(**_kwargs: object) -> None:
        raise OSError("no device")

    main_ns.ns["MAX7219"] = _boom

    with pytest.raises(_StopLoop):
        main_ns.ns["main"]()

    assert {"diag": "init_err"} in emitted
    assert "init_err" in main_ns.status.calls


def test_main_runs_after_successful_init(main_ns: object) -> None:
    main_ns.ns["time"] = _CountdownTime(stop_after=99)
    main_ns.ns["emit"] = lambda _obj: None
    main_ns.ns["MAX7219"] = lambda **_kwargs: _FakeDisplay()
    calls = {"run": 0}

    def _fake_run(display: object) -> None:
        calls["run"] += 1
        raise _StopLoop

    main_ns.ns["run"] = _fake_run

    with pytest.raises(_StopLoop):
        main_ns.ns["main"]()

    assert calls["run"] == 1
