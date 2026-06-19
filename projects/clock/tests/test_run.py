"""Host CPython tests for the clock project firmware.

Covers emit(), _run_window() GPS collection with snake animation, and the
run()/main() loops.  The loops are infinite; tests escape them with a countdown
``time`` whose ``sleep_ms`` raises a BaseException after a set number of calls
(run()/main() only catch ``Exception``).
"""

from __future__ import annotations

import json

import pytest

_GPRMC_VALID = "$GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*6A"


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
    """Display stand-in with a framebuffer for snake pixel tests."""

    def __init__(self, num_modules: int = 4) -> None:
        self.n = num_modules
        self.buf = bytearray(8 * num_modules)

    def clear_buf(self) -> None:
        for i in range(len(self.buf)):
            self.buf[i] = 0

    def refresh(self) -> None:
        pass


class _FakeGPS:
    """Scripted NMEA reader; returns None once the queue is empty."""

    def __init__(self, lines: list[str]) -> None:
        self._q = list(lines)

    def readline(self) -> str | None:
        return self._q.pop(0) if self._q else None


def _make_snake(display_h: int = 16, length: int = 7) -> list:
    """Build an initial snake body matching firmware's startup state."""
    y = display_h // 2
    return [(i, y) for i in range(length)]


# ---------------------------------------------------------------------------
# emit
# ---------------------------------------------------------------------------


def test_emit_writes_one_json_line(main_ns: object, capsys: pytest.CaptureFixture) -> None:
    main_ns.ns["emit"]({"fix": True, "day": "MONDAY"})
    out = capsys.readouterr().out.strip()
    assert json.loads(out) == {"fix": True, "day": "MONDAY"}


# ---------------------------------------------------------------------------
# _run_window
# ---------------------------------------------------------------------------


def test_run_window_emits_gps_data(main_ns: object, capsys: pytest.CaptureFixture) -> None:
    """Valid NMEA line produces a JSON signal result with satellite data."""
    snake = _make_snake()
    main_ns.ns["_run_window"](_FakeGPS([_GPRMC_VALID]), None, _FakeDisplay(), _FakeDisplay(), snake)
    out = capsys.readouterr().out.strip()
    data = json.loads(out)
    assert "window_ms" in data
    assert "sats_in_use" in data


def test_run_window_emits_no_data_when_silent(
    main_ns: object, capsys: pytest.CaptureFixture
) -> None:
    """No NMEA lines produce a no_data diagnostic."""
    snake = _make_snake()
    main_ns.ns["_run_window"](_FakeGPS([]), None, _FakeDisplay(), _FakeDisplay(), snake)
    out = capsys.readouterr().out.strip()
    assert json.loads(out) == {"diag": "no_data"}


def test_run_window_passes_cached_date_through(main_ns: object) -> None:
    """cached_date is returned unchanged when no new date is seen."""
    snake = _make_snake()
    result = main_ns.ns["_run_window"](
        _FakeGPS([]), "2025-06-01", _FakeDisplay(), _FakeDisplay(), snake
    )
    assert result == "2025-06-01"


# ---------------------------------------------------------------------------
# run loop
# ---------------------------------------------------------------------------


def test_run_enters_streaming_state(main_ns: object) -> None:
    main_ns.ns["time"] = _CountdownTime(stop_after=1)
    main_ns.ns["emit"] = lambda _obj: None

    with pytest.raises(_StopLoop):
        main_ns.ns["run"](_FakeGPS([]), _FakeDisplay(), _FakeDisplay())

    assert "streaming" in main_ns.status.calls


def test_run_recovers_from_read_error(main_ns: object) -> None:
    main_ns.ns["time"] = _CountdownTime(stop_after=1)
    main_ns.ns["emit"] = lambda _obj: None

    class _FaultGPS:
        def readline(self) -> str | None:
            raise OSError("UART fault")

    with pytest.raises(_StopLoop):
        main_ns.ns["run"](_FaultGPS(), _FakeDisplay(), _FakeDisplay())

    assert "read_err" in main_ns.status.calls


# ---------------------------------------------------------------------------
# main entry point
# ---------------------------------------------------------------------------


def test_main_reports_init_error_and_retries(main_ns: object) -> None:
    main_ns.ns["time"] = _CountdownTime(stop_after=2)
    emitted: list[dict] = []
    main_ns.ns["emit"] = lambda obj: emitted.append(dict(obj))

    def _boom(**_kwargs: object) -> None:
        raise OSError("no device")

    main_ns.ns["gps_connect"] = _boom
    main_ns.ns["display_connect"] = _boom

    with pytest.raises(_StopLoop):
        main_ns.ns["main"]()

    assert {"diag": "init_err"} in emitted
    assert "init_err" in main_ns.status.calls


def test_main_runs_after_successful_init(main_ns: object) -> None:
    main_ns.ns["time"] = _CountdownTime(stop_after=99)
    main_ns.ns["emit"] = lambda _obj: None
    main_ns.ns["gps_connect"] = lambda **_kwargs: _FakeGPS([])
    main_ns.ns["display_connect"] = lambda **_kwargs: _FakeDisplay()
    calls = {"run": 0}

    def _fake_run(gps: object, display_top: object, display_bot: object) -> None:
        calls["run"] += 1
        raise _StopLoop

    main_ns.ns["run"] = _fake_run

    with pytest.raises(_StopLoop):
        main_ns.ns["main"]()

    assert calls["run"] == 1
