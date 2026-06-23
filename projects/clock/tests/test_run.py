"""Host CPython tests for the clock project firmware."""

from __future__ import annotations

import json

import pytest

from pixel_display import Frame

_RMC_FIX = "$GPRMC,235958,A,3723.2475,N,12158.3416,W,0.0,0.0,230626,0.0,E*69"


class _StopLoop(BaseException):
    """Sentinel that escapes the run()/main() `except Exception` guards."""


class _CountdownTime:
    """time stub whose sleep_ms raises _StopLoop after `stop_after` calls."""

    def __init__(self, stop_after: int) -> None:
        """Initialise the countdown."""
        self.t = 0
        self._stop = stop_after
        self._sleeps = 0

    def ticks_ms(self) -> int:
        """Return a steadily increasing millisecond counter."""
        self.t += 1
        return self.t

    def ticks_diff(self, a: int, b: int) -> int:
        """Return the difference between two tick values."""
        return a - b

    def sleep_ms(self, _ms: int) -> None:
        """Count sleeps and raise the stop sentinel when the limit is reached."""
        self._sleeps += 1
        if self._sleeps >= self._stop:
            raise _StopLoop


class _FakeDisplay:
    """Display stand-in recording abstract frame renders."""

    def __init__(self) -> None:
        """Initialise an empty call log."""
        self.shown: list[object] = []

    def show(self, frame: object) -> None:
        """Record the requested frame."""
        self.shown.append(frame)


class _FakeGPS:
    """GPS stand-in returning scripted lines or raising scripted exceptions."""

    def __init__(self, lines: list) -> None:
        """Store scripted readline outcomes."""
        self._lines = list(lines)

    def readline(self) -> str | None:
        """Return the next scripted line, or None when exhausted."""
        if not self._lines:
            return None
        line = self._lines.pop(0)
        if isinstance(line, Exception):
            raise line
        return line


class _FakeRTC:
    """RTC stand-in supporting MicroPython's datetime getter/setter shape."""

    def __init__(self) -> None:
        """Start at a deterministic midnight."""
        self.value = (2026, 1, 1, 3, 0, 0, 0, 0)

    def datetime(self, value: tuple | None = None) -> tuple | None:
        """Get or set the stored RTC datetime tuple."""
        if value is None:
            return self.value
        self.value = tuple(value)
        return None


def test_emit_writes_one_json_line(main_ns: object, capsys: pytest.CaptureFixture) -> None:
    """emit() writes exactly one compact JSON object per line."""
    main_ns.ns["emit"]({"fix": True, "day": "TUE"})
    out = capsys.readouterr().out.strip()
    assert json.loads(out) == {"fix": True, "day": "TUE"}


def test_run_waits_for_gps_before_first_fix(main_ns: object) -> None:
    """The matrix shows a GPS wait state until a complete fix arrives."""
    main_ns.ns["time"] = _CountdownTime(stop_after=1)
    display = _FakeDisplay()

    with pytest.raises(_StopLoop):
        main_ns.ns["run"](_FakeGPS([None]), display, _FakeRTC())

    assert len(display.shown) == 1
    assert _same_frame(display.shown[0], Frame.text_lines(("GPS", "WAIT")))
    assert "streaming" in main_ns.status.calls


def test_run_syncs_rtc_and_displays_current_time_and_date(main_ns: object) -> None:
    """A valid RMC fix sets the RTC and renders local time over date."""
    main_ns.ns["time"] = _CountdownTime(stop_after=1)
    emitted: list[dict] = []
    main_ns.ns["emit"] = lambda obj: emitted.append(dict(obj))
    display = _FakeDisplay()
    rtc = _FakeRTC()

    with pytest.raises(_StopLoop):
        main_ns.ns["run"](_FakeGPS([_RMC_FIX]), display, rtc)

    assert rtc.value == (2026, 6, 23, 1, 15, 59, 58, 0)
    assert _same_frame(display.shown[-1], Frame.text_lines(("15:59", "6/23")))
    assert len(emitted) == 1
    assert emitted[0]["fix"] is True
    assert emitted[0]["lon"] == pytest.approx(-121.97236, abs=1e-5)
    assert emitted[0]["offset_h"] == -8
    assert emitted[0]["local"] == "2026-06-23T15:59:58"
    assert emitted[0]["day"] == "TUE"
    assert emitted[0]["t"] == 1


def test_run_reports_read_errors_and_keeps_loop_alive(main_ns: object) -> None:
    """UART/parser exceptions emit a diagnostic and use the read-error LED state."""
    main_ns.ns["time"] = _CountdownTime(stop_after=1)
    emitted: list[dict] = []
    main_ns.ns["emit"] = lambda obj: emitted.append(dict(obj))

    with pytest.raises(_StopLoop):
        main_ns.ns["run"](_FakeGPS([OSError("uart")]), _FakeDisplay(), _FakeRTC())

    assert {"diag": "read_err"} in emitted
    assert "read_err" in main_ns.status.calls


def test_main_reports_init_error_and_retries(main_ns: object) -> None:
    """main() emits init_err and retries when GPS/display setup fails."""
    main_ns.ns["time"] = _CountdownTime(stop_after=2)
    emitted: list[dict] = []
    main_ns.ns["emit"] = lambda obj: emitted.append(dict(obj))

    def _boom(**_kwargs: object) -> None:
        raise OSError("no display")

    main_ns.ns["MAX7219"] = _boom

    with pytest.raises(_StopLoop):
        main_ns.ns["main"]()

    assert {"diag": "init_err"} in emitted
    assert "init_err" in main_ns.status.calls


def test_main_runs_after_successful_init(main_ns: object) -> None:
    """main() wires board pins into the GPS, display, RTC, and run loop."""
    main_ns.ns["time"] = _CountdownTime(stop_after=99)
    main_ns.ns["emit"] = lambda _obj: None
    created: dict = {}

    def _display(**kwargs: object) -> _FakeDisplay:
        created["display"] = dict(kwargs)
        return _FakeDisplay()

    def _gps(**kwargs: object) -> _FakeGPS:
        created["gps"] = dict(kwargs)
        return _FakeGPS([])

    def _run(gps: object, display: object, rtc: object) -> None:
        created["run"] = (gps, display, rtc)
        raise _StopLoop

    main_ns.ns["MAX7219"] = _display
    main_ns.ns["GPS"] = _gps
    main_ns.ns["RTC"] = _FakeRTC
    main_ns.ns["run"] = _run

    with pytest.raises(_StopLoop):
        main_ns.ns["main"]()

    assert created["display"] == {
        "spi_id": 1,
        "sck": 26,
        "mosi": 27,
        "cs": 28,
        "width_pixels": 32,
        "height_pixels": 16,
        "intensity_min": 0,
        "intensity_max": 15,
        "intensity_limit": 0.2,
    }
    assert created["gps"] == {"bus_id": 0, "tx": 0, "rx": 1}
    assert isinstance(created["run"][2], _FakeRTC)


def _same_frame(left: object, right: object) -> bool:
    """Return whether two frame-like objects hold identical pixels."""
    return (
        left.width == right.width
        and left.height == right.height
        and left.channels == right.channels
        and bytes(left.data) == bytes(right.data)
    )
