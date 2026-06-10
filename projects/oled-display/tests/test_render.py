"""Host CPython integration tests for render() in oled-display.

Loads render() out of main.py (see conftest.main_ns) and drives it with a
scripted fake driver to assert the demo's behavioural contract:

  1. the counter increments once per ~second of (fake) time, monotonically;
  2. a transient I²C fault on show() flips the LED read_err -> streaming and
     the loop survives;
  3. emitted lines stay valid JSON.

The fake driver raises a non-OSError sentinel to end render()'s infinite loop
(its `except` catches OSError only, so the sentinel propagates).
"""

import io
import itertools
import json
from contextlib import redirect_stdout

import pytest


def test_counter_increments_once_per_second(main_ns):
    driver = _ScriptedDriver([None] * 100)  # 100 clean frames, then sentinel
    records = _run_render(main_ns, driver)
    counts = [r["count"] for r in records if "count" in r]

    assert len(counts) >= 2
    assert counts == list(range(1, len(counts) + 1))  # 1, 2, 3, ... no gaps

    period = main_ns.ns["_COUNTER_PERIOD_MS"]
    frame = main_ns.ns["_FRAME_MS"]
    times = [r["t"] for r in records if "count" in r]
    for earlier, later in itertools.pairwise(times):
        # Increment fires the first frame past the period boundary, so each
        # gap lands in [period, period + one frame).
        assert period <= later - earlier <= period + frame


def test_read_err_recovers_and_keeps_streaming(main_ns):
    driver = _ScriptedDriver([None, OSError, None])
    records = _run_render(main_ns, driver)

    assert main_ns.status.calls == ["streaming", "read_err", "streaming"]
    assert any(r.get("diag") == "read_err" for r in records)


def test_frames_are_drawn(main_ns):
    driver = _ScriptedDriver([None] * 5)
    _run_render(main_ns, driver)
    assert driver.show_calls >= 5


def _run_render(main_ns, driver):
    """Drive render() until the driver's script is exhausted; return parsed JSON."""
    render = main_ns.ns["render"]
    buf = io.StringIO()
    with redirect_stdout(buf), pytest.raises(_StopLoopError):
        render(driver)
    return [json.loads(line) for line in buf.getvalue().splitlines() if line.strip()]


class _StopLoopError(Exception):
    """Sentinel raised by the fake driver to escape render()'s loop.

    render() catches only OSError, so any other Exception subclass propagates
    and ends the test deterministically.
    """


class _ScriptedDriver:
    """Driver stand-in: pixel/fill are no-ops; show() is scripted.

    `script` is consumed one item per show() call:
      - None  -> the flush succeeds;
      - an exception *class* (e.g. OSError) -> raised to exercise recovery.
    When the script is exhausted, show() raises _StopLoopError to end the loop.
    """

    def __init__(self, script) -> None:
        self._script = list(script)
        self.show_calls = 0

    def pixel(self, x, y, color) -> None:
        return None

    def fill(self, color) -> None:
        return None

    def show(self) -> None:
        self.show_calls += 1
        if not self._script:
            raise _StopLoopError
        item = self._script.pop(0)
        if item is not None:
            raise item("scripted")
