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

import os
import pathlib
import sys
from collections import namedtuple

import pytest

from micropython_stubs.testing import firmware_namespace

_HERE = pathlib.Path(__file__).parent.resolve()
_FIRMWARE = _HERE.parent / "firmware" / "main.py"

_FIRMWARE_DIR = str(_FIRMWARE.parent)
if _FIRMWARE_DIR not in sys.path:
    sys.path.insert(0, _FIRMWARE_DIR)

import nmea  # noqa: E402

_KEEP_FUNCS = {"emit", "stream", "main", "_run_window"}
Board = namedtuple("Board", ("name", "uart_id", "tx", "rx"))
_TEST_BOARD = Board(name="RP2040-Zero", uart_id=0, tx=0, rx=1)

_GPGGA = "$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47"
_GPGSA = "$GPGSA,A,3,01,02,03,04,05,06,07,08,09,10,11,12,2.0,1.0,1.8*3B"
_GPGSV = "$GPGSV,3,1,09,01,40,083,46,02,17,308,41,12,07,344,39,14,22,228,45*75"

_TEST_WINDOW_MS = 2


def _make_main_ns():
    """Create a fresh AST-loaded main.py namespace with fakes."""
    return firmware_namespace(
        _FIRMWARE,
        _KEEP_FUNCS,
        os=os,
        namedtuple=namedtuple,
        BOARD=_TEST_BOARD,
        nmea_checksum_valid=nmea.nmea_checksum_valid,
        parse_sentence=nmea.parse_sentence,
        apply_parsed=nmea.apply_parsed,
        build_utc_full=nmea.build_utc_full,
    )


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
    """Exercise stream() for `stop_after` emit() calls and return the recorded objects."""
    stream = main_ns.ns["stream"]
    cap = _CapturingEmit(stop_after)
    main_ns.ns["emit"] = cap
    main_ns.ns["WINDOW_MS"] = _TEST_WINDOW_MS
    with pytest.raises(_StopLoopError):
        stream(_FakeGPS(sentences))
    return cap.calls


def test_stream_emits_parsed_position() -> None:
    main_ns = _make_main_ns()
    calls = _run(main_ns, [_GPGGA])
    assert calls[0]["lat"] is not None
    assert calls[0]["lon"] is not None
    assert "window_ms" in calls[0]


def test_stream_batch_parses_multiple_sentence_types() -> None:
    main_ns = _make_main_ns()
    main_ns.ns["WINDOW_MS"] = 20
    cap = _CapturingEmit(1)
    main_ns.ns["emit"] = cap
    with pytest.raises(_StopLoopError):
        main_ns.ns["stream"](_FakeGPS([_GPGGA, _GPGSA]))
    assert cap.calls[0]["lat"] is not None
    assert cap.calls[0]["hdop"] is not None


def test_stream_emits_no_data_when_gps_silent() -> None:
    main_ns = _make_main_ns()
    calls = _run(main_ns, [])
    assert calls[0]["diag"] == "no_data"


def test_stream_batch_has_required_keys() -> None:
    main_ns = _make_main_ns()
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


def test_stream_read_err_calls_status_read_err() -> None:
    """OSError from readline() is caught; status.read_err() fires and stream recovers."""
    main_ns = _make_main_ns()

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
    cap = _CapturingEmit(2)
    main_ns.ns["emit"] = cap
    with pytest.raises(_StopLoopError):
        main_ns.ns["stream"](_OsErrorOnFirstCall())

    diags = [c.get("diag") for c in cap.calls if "diag" in c]
    assert "read_err" in diags
    assert "read_err" in main_ns.status.calls


def test_stream_recovers_and_continues_after_read_err() -> None:
    """After a read_err, status returns to streaming and the loop continues."""
    main_ns = _make_main_ns()

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
