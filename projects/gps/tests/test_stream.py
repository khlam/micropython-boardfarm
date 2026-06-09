"""Host CPython tests for stream() in the gps project firmware.

Covers the happy path (sentences collected and emitted), the empty-window path
(no data → {"diag": "no_data"}), and the read_err recovery path.

stream() is an infinite loop. Tests escape it by replacing `emit` in the
namespace with a _CapturingEmit that raises _StopLoopError (a BaseException
subclass) after a configured number of calls. Because stream() only catches
`Exception`, the BaseException propagates out cleanly.

WINDOW_MS is overridden to a small value so the inner ticks_diff-bounded loop
exits in a handful of ticks_ms() calls, keeping tests fast.
"""

from __future__ import annotations

import pytest

# NMEA sentences used across tests.
_GPGGA = "$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47"
_GPGGA_NO_FIX = "$GPGGA,123519,4807.038,N,01131.000,E,0,08,0.9,545.4,M,46.9,M,,*41"
_GPGSA = "$GPGSA,A,3,01,02,03,04,05,06,07,08,09,10,11,12,2.0,1.0,1.8*21"
_GPGSV = "$GPGSV,3,1,09,01,40,083,46,02,17,308,41,12,07,344,39,14,22,228,45*75"

# Override WINDOW_MS to this small value so the inner loop exits after ~2
# ticks_ms() calls (fake_time steps by 1; 2 steps push diff past the threshold).
_TEST_WINDOW_MS = 2


class _StopLoopError(BaseException):
    """Sentinel that escapes stream()'s `except Exception` guard."""


class _CapturingEmit:
    """Drop-in replacement for emit() that records calls and then raises."""

    def __init__(self, stop_after: int = 1) -> None:
        """Initialise with an empty call log and stop threshold.

        Args:
            stop_after: Raise _StopLoopError after this many emit() calls.
        """
        self.calls: list[dict] = []
        self._stop = stop_after

    def __call__(self, obj: dict) -> None:
        """Record obj and raise _StopLoopError once the threshold is reached."""
        self.calls.append(dict(obj))
        if len(self.calls) >= self._stop:
            raise _StopLoopError


class _FakeGPS:
    """Scripted GPS NMEA reader."""

    def __init__(self, sentences: list[str]) -> None:
        """Store the sentence queue.

        Args:
            sentences: Sentences to return in order. Once exhausted, readline()
                returns None indefinitely (mimics a silent GPS).
        """
        self._queue: list[str] = list(sentences)

    def readline(self) -> str | None:
        """Pop and return the next queued sentence, or None when empty."""
        return self._queue.pop(0) if self._queue else None


def _run(main_ns: object, sentences: list[str], stop_after: int = 1) -> list[dict]:
    """Exercise stream() for `stop_after` emit() calls and return the recorded objects.

    Overrides WINDOW_MS to _TEST_WINDOW_MS, replaces emit() with a _CapturingEmit,
    passes a _FakeGPS directly to stream(), then absorbs _StopLoopError via
    pytest.raises.
    """
    stream = main_ns.ns["stream"]
    cap = _CapturingEmit(stop_after)
    main_ns.ns["emit"] = cap
    main_ns.ns["WINDOW_MS"] = _TEST_WINDOW_MS
    with pytest.raises(_StopLoopError):
        stream(_FakeGPS(sentences))
    return cap.calls


def test_stream_emits_parsed_position(main_ns: object) -> None:
    calls = _run(main_ns, [_GPGGA])
    assert calls[0]["lat"] is not None
    assert calls[0]["lon"] is not None
    assert "window_ms" in calls[0]


def test_stream_batch_parses_multiple_sentence_types(main_ns: object) -> None:
    main_ns.ns["WINDOW_MS"] = 20
    cap = _CapturingEmit(1)
    main_ns.ns["emit"] = cap
    with pytest.raises(_StopLoopError):
        main_ns.ns["stream"](_FakeGPS([_GPGGA, _GPGSA]))
    assert cap.calls[0]["lat"] is not None
    assert cap.calls[0]["hdop"] is not None


def test_stream_emits_no_data_when_gps_silent(main_ns: object) -> None:
    calls = _run(main_ns, [])
    assert calls[0]["diag"] == "no_data"


def test_stream_batch_has_required_keys(main_ns: object) -> None:
    calls = _run(main_ns, [_GPGGA])
    batch = calls[0]
    assert {
        "window_ms",
        "sats_in_use",
        "sats_in_view",
        "hdop",
        "vdop",
        "pdop",
        "lat",
        "lon",
        "signals",
    } <= set(batch)


def test_stream_read_err_calls_status_read_err(main_ns: object) -> None:
    """OSError from readline() is caught; status.read_err() fires and stream recovers."""

    class _OsErrorOnFirstCall(_FakeGPS):
        def __init__(self) -> None:
            super().__init__([])
            self._calls = 0

        def readline(self) -> str | None:
            self._calls += 1
            if self._calls == 1:
                raise OSError("UART fault")
            return None

    main_ns.ns["WINDOW_MS"] = _TEST_WINDOW_MS
    cap = _CapturingEmit(2)  # 1st call = read_err diag; 2nd = no_data after recovery
    main_ns.ns["emit"] = cap
    with pytest.raises(_StopLoopError):
        main_ns.ns["stream"](_OsErrorOnFirstCall())

    diags = [c.get("diag") for c in cap.calls if "diag" in c]
    assert "read_err" in diags
    assert "read_err" in main_ns.status.calls


@pytest.fixture
def parse_sentence(main_ns: object):
    """Return the _parse_sentence function from the loaded firmware namespace."""
    return main_ns.ns["_parse_sentence"]


def test_parse_sentence_gga_returns_position(parse_sentence) -> None:
    _, _, _, _, position = parse_sentence(_GPGGA)
    assert position["lat"] == pytest.approx(48.1173, abs=1e-4)
    assert position["lon"] == pytest.approx(11.5167, abs=1e-4)


def test_parse_sentence_gga_no_fix_returns_empty_position(parse_sentence) -> None:
    _, _, _, _, position = parse_sentence(_GPGGA_NO_FIX)
    assert position == {}


def test_parse_sentence_gsa_returns_dop_and_in_use(parse_sentence) -> None:
    _, in_use, _, dop, _ = parse_sentence(_GPGSA)
    assert len(in_use) == 12
    assert dop["pdop"] == pytest.approx(2.0)
    assert dop["hdop"] == pytest.approx(1.0)
    assert dop["vdop"] == pytest.approx(1.8)


def test_parse_sentence_gsv_returns_signals_and_in_view(parse_sentence) -> None:
    signals, _, total_in_view, _, _ = parse_sentence(_GPGSV)
    assert total_in_view["GP"] == 9
    assert len(signals) == 4
    assert all(s["sys"] == "GP" and s["snr"] > 0 for s in signals.values())


def test_parse_sentence_gsv_repeated_epoch_overwrites_not_appends(main_ns: object) -> None:
    parse_sentence = main_ns.ns["_parse_sentence"]
    signals: dict = {}
    for _ in range(3):
        new_signals, _, _, _, _ = parse_sentence(_GPGSV)
        signals.update(new_signals)
    assert len(signals) == 4


def test_parse_sentence_unknown_tag_returns_empty(parse_sentence) -> None:
    signals, in_use, total_in_view, dop, position = parse_sentence(
        "$GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*6A"
    )
    assert signals == {} and in_use == set() and total_in_view == {}
    assert dop == {} and position == {}


def test_stream_recovers_and_continues_after_read_err(main_ns: object) -> None:
    """After a read_err, status returns to streaming and the loop continues."""

    class _FailThenRecover(_FakeGPS):
        def __init__(self) -> None:
            super().__init__([])
            self._calls = 0

        def readline(self) -> str | None:
            self._calls += 1
            if self._calls == 1:
                raise OSError("transient fault")
            return None

    main_ns.ns["WINDOW_MS"] = _TEST_WINDOW_MS
    cap = _CapturingEmit(2)
    main_ns.ns["emit"] = cap
    with pytest.raises(_StopLoopError):
        main_ns.ns["stream"](_FailThenRecover())

    assert main_ns.status.calls[-1] == "streaming"
