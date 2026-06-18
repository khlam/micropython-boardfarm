"""Host CPython tests for the clock project firmware.

Covers the per-line RTC update (_apply_line), the GPS-pump helper, the display
advance helper, and the run()/main() loops. The loops are infinite; tests escape
them with a countdown ``time`` whose ``sleep_ms`` raises a BaseException after a
set number of calls (run()/main() only catch ``Exception``).
"""

from __future__ import annotations

import json
from typing import ClassVar

import pytest

# RMC carries UTC time + date + longitude together. lon 11.5167 -> +1h offset.
_GPRMC_VALID = "$GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*6A"
_GPRMC_VOID = "$GPRMC,123519,V,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*7D"
_GPZDA = "$GPZDA,131415,01,06,2025,00,00*49"  # time + date but no longitude


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


class _FakeRTC:
    """RTC stand-in: datetime(tuple) stores, datetime() returns."""

    def __init__(self) -> None:
        self.set_to: tuple | None = None

    def datetime(self, dt: tuple | None = None) -> tuple | None:
        if dt is None:
            return self.set_to
        self.set_to = dt
        return None


class _FakeCycle:
    """DisplayCycle stand-in recording start()/step() counts."""

    instances: ClassVar[list] = []

    def __init__(self, display: object, rtc: object) -> None:
        self.display = display
        self.rtc = rtc
        self.started = 0
        self.steps = 0
        _FakeCycle.instances.append(self)

    def start(self) -> None:
        self.started += 1

    def step(self) -> None:
        self.steps += 1


class _FakeDisplay:
    """Display stand-in recording show_auto/wiggle_step calls."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def show_auto(self, text: str, _fn: object = None) -> None:
        self.calls.append(("show_auto", text))

    def wiggle_step(self) -> None:
        self.calls.append(("wiggle_step",))


class _FakeGPS:
    """Scripted NMEA reader; returns None once the queue is empty."""

    def __init__(self, lines: list[str]) -> None:
        self._q = list(lines)

    def readline(self) -> str | None:
        return self._q.pop(0) if self._q else None


# ---------------------------------------------------------------------------
# emit
# ---------------------------------------------------------------------------


def test_emit_writes_one_json_line(main_ns: object, capsys: pytest.CaptureFixture) -> None:
    main_ns.ns["emit"]({"fix": True, "day": "MONDAY"})
    out = capsys.readouterr().out.strip()
    assert json.loads(out) == {"fix": True, "day": "MONDAY"}


# ---------------------------------------------------------------------------
# _apply_line
# ---------------------------------------------------------------------------


def test_apply_line_sets_rtc_and_returns_payload(main_ns: object) -> None:
    rtc = _FakeRTC()
    payload = main_ns.ns["_apply_line"](_GPRMC_VALID, rtc)
    assert payload["fix"] is True
    assert payload["offset_h"] == 1  # lon 11.5167 -> round(0.77) = 1
    assert payload["lon"] == pytest.approx(11.5167, abs=1e-4)
    assert payload["local"].startswith("2094-03-23T13:35:19")  # 12:35:19 UTC + 1h
    assert payload["day"] in {
        "MONDAY",
        "TUESDAY",
        "WEDNESDAY",
        "THURSDAY",
        "FRIDAY",
        "SATURDAY",
        "SUNDAY",
    }
    assert rtc.set_to is not None
    assert rtc.set_to[4] == 13  # local hour stored in the RTC tuple


@pytest.mark.parametrize(
    "line",
    [
        _GPRMC_VALID[:-2] + "00",  # corrupted checksum
        _GPRMC_VOID,  # status V -> no usable fields
        _GPZDA,  # time + date but no longitude
    ],
    ids=["bad_checksum", "void_status", "no_longitude"],
)
def test_apply_line_returns_none(main_ns: object, line: str) -> None:
    rtc = _FakeRTC()
    assert main_ns.ns["_apply_line"](line, rtc) is None
    assert rtc.set_to is None


# ---------------------------------------------------------------------------
# _read_payload
# ---------------------------------------------------------------------------


def test_read_payload_none_when_gps_silent(main_ns: object) -> None:
    assert main_ns.ns["_read_payload"](_FakeGPS([]), _FakeRTC()) is None


def test_read_payload_applies_rmc(main_ns: object) -> None:
    rtc = _FakeRTC()
    payload = main_ns.ns["_read_payload"](_FakeGPS([_GPRMC_VALID]), rtc)
    assert payload["fix"] is True
    assert rtc.set_to is not None


# ---------------------------------------------------------------------------
# _advance_display
# ---------------------------------------------------------------------------


def test_advance_display_steps_cycle_with_fix(main_ns: object) -> None:
    cyc = _FakeCycle(_FakeDisplay(), None)
    out = main_ns.ns["_advance_display"](_FakeDisplay(), cyc, have_fix=True, wiggle_tick=5)
    assert cyc.steps == 1
    assert out == 5  # wiggle tick unchanged while a fix drives the cycle


def test_advance_display_wiggles_placeholder_without_fix(main_ns: object) -> None:
    display = _FakeDisplay()
    # wiggle_tick far in the past so ticks_diff exceeds _WIGGLE_MS.
    out = main_ns.ns["_advance_display"](display, None, have_fix=False, wiggle_tick=-10_000)
    assert ("wiggle_step",) in display.calls
    assert out != -10_000  # tick advanced to "now"


# ---------------------------------------------------------------------------
# run loop
# ---------------------------------------------------------------------------


def test_run_sets_rtc_and_starts_cycle_on_first_fix(main_ns: object) -> None:
    main_ns.ns["time"] = _CountdownTime(stop_after=1)  # escape after one iteration
    captured: list[dict] = []
    main_ns.ns["emit"] = lambda obj: captured.append(dict(obj))
    rtc = _FakeRTC()
    main_ns.ns["RTC"] = lambda: rtc
    _FakeCycle.instances.clear()
    main_ns.ns["DisplayCycle"] = _FakeCycle
    display = _FakeDisplay()

    with pytest.raises(_StopLoop):
        main_ns.ns["run"](_FakeGPS([_GPRMC_VALID]), display)

    assert ("show_auto", "WAITING FOR GPS") in display.calls  # pre-fix placeholder
    assert rtc.set_to is not None and rtc.set_to[4] == 13
    assert captured and captured[0]["fix"] is True and "t" in captured[0]
    cyc = _FakeCycle.instances[0]
    assert cyc.started == 1
    assert cyc.steps == 1
    assert "streaming" in main_ns.status.calls


def test_run_recovers_from_read_error(main_ns: object) -> None:
    main_ns.ns["time"] = _CountdownTime(stop_after=1)
    main_ns.ns["emit"] = lambda _obj: None
    main_ns.ns["RTC"] = _FakeRTC
    _FakeCycle.instances.clear()
    main_ns.ns["DisplayCycle"] = _FakeCycle

    class _FaultGPS:
        def readline(self) -> str | None:
            raise OSError("UART fault")

    with pytest.raises(_StopLoop):
        main_ns.ns["run"](_FaultGPS(), _FakeDisplay())

    assert "read_err" in main_ns.status.calls


# ---------------------------------------------------------------------------
# main entry point
# ---------------------------------------------------------------------------


def test_main_reports_init_error_and_retries(main_ns: object) -> None:
    main_ns.ns["time"] = _CountdownTime(stop_after=2)  # boot pause, then init-err pause
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

    def _fake_run(gps: object, display: object) -> None:
        calls["run"] += 1
        raise _StopLoop

    main_ns.ns["run"] = _fake_run

    with pytest.raises(_StopLoop):
        main_ns.ns["main"]()

    assert calls["run"] == 1
