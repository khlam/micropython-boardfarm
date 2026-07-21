"""Host CPython tests for the event-driven Sensor and the gauge state machine.

These cover the two properties the interrupt refactor exists for: that
``Sensor.poll`` never blocks and recovers from a fault or a stalled interrupt on
a ticks deadline (no ``sleep``), and that the ``Gauge`` unlock transition is
spread across frames rather than slept through. Timing is driven by explicit
``now`` values, so the tests are deterministic without a real clock.
"""

from __future__ import annotations

import pathlib
import sys

_FIRMWARE_DIR = str(pathlib.Path(__file__).parent.parent / "firmware")
if _FIRMWARE_DIR not in sys.path:
    sys.path.insert(0, _FIRMWARE_DIR)

import gauge  # noqa: E402
from gauge import Gauge, Sensor  # noqa: E402


def test_sensor_reads_only_when_data_ready():
    """poll() reads on the data-ready flag and caches the last sample otherwise."""
    tof = _FakeTof()
    sensor = Sensor(tof, [].append)

    assert sensor.poll(0) == ("err", 0)  # nothing ready yet: cached error, no read
    assert tof.reads == 0

    tof.set(120)
    assert sensor.poll(10) == ("in", 120)
    assert tof.reads == 1
    assert sensor.poll(20) == ("in", 120)  # no new sample: cached, still no extra read
    assert tof.reads == 1


def test_sensor_classifies_out_of_range():
    """A reading at/above OUT_OF_RANGE_MM classifies as a confirmed release sample."""
    tof = _FakeTof()
    sensor = Sensor(tof, [].append)
    tof.set(gauge.OUT_OF_RANGE_MM)
    assert sensor.poll(0) == ("out", 0)


def test_sensor_none_reports_permanent_error():
    """Without a sensor, poll() reports error and never touches hardware."""
    sensor = Sensor(None, [].append)
    assert sensor.poll(0) == ("err", 0)
    assert sensor.poll(9999) == ("err", 0)


def test_sensor_recovery_is_deadline_based_no_sleep():
    """A read fault arms a ticks-deadline recovery; stop()/start() defer, no sleep."""
    tof = _FakeTof()
    events: list = []
    sensor = Sensor(tof, events.append)

    tof.set(100)
    tof.raise_on_read = True
    assert sensor.poll(0) == ("err", 0)  # read raises: recovery armed, nothing slept
    assert tof.stops == 0 and tof.starts == 0  # restart deferred to the deadline
    assert events[-1]["diag"] == "read_err"

    # Before the pause elapses, still recovering — no restart yet.
    assert sensor.poll(gauge._READ_ERR_PAUSE_MS - 1) == ("err", 0)
    assert tof.starts == 0

    # At the deadline, exactly one stop()/start() re-arms continuous ranging.
    tof.raise_on_read = False
    sensor.poll(gauge._READ_ERR_PAUSE_MS)
    assert tof.stops == 1 and tof.starts == 1


def test_sensor_stall_triggers_reranging():
    """No fresh sample for _SENSOR_STALL_MS re-arms ranging (missed-edge watchdog)."""
    tof = _FakeTof()
    events: list = []
    sensor = Sensor(tof, events.append)

    tof.set(150)
    assert sensor.poll(0) == ("in", 150)  # fresh sample resets the stall clock
    # data_ready stays False afterward; the stall window then arms recovery.
    assert sensor.poll(gauge._SENSOR_STALL_MS) == ("err", 0)
    assert events[-1]["diag"] == "sensor_stall"


def test_gauge_locks_immediately_on_in_range_then_shows_glow():
    """The first in-range reading locks on that frame and switches to the glow."""
    strip = _FakeStrip()
    events: list = []
    g = Gauge(strip, _FakeLed(), 4, events.append)

    # An out-of-range sample keeps the LED effects on screen.
    assert g.step(("out", 0), 0) is None
    assert strip.frames[-1] == [(1, 2, 3)] * 4

    # The very next in-range sample locks — no steady-hold wait.
    assert g.step(("in", 200), 10) == "locked"
    assert any(e.get("diag") == "lock" for e in events)

    # Locked: an in-range sample renders a glow frame, not the LED display frame.
    assert g.step(("in", 200), 20) is None
    assert strip.frames[-1] != [(1, 2, 3)] * 4


def test_gauge_transition_spreads_across_frames_without_blocking():
    """The unlock sweep advances one LED per _TRANSITION_STEP_MS, never blocking."""
    strip = _FakeStrip()
    g = Gauge(strip, _FakeLed(), 4, [].append)

    g.step(("in", 200), 0)  # -> locked immediately
    g.step(("in", 200), 1)  # establish a glow position

    base = 1
    assert g.step(("out", 0), base) is None  # release timer starts
    assert g.step(("out", 0), base + gauge.RELEASE_MS) is None  # enters the sweep

    frames_before = len(strip.frames)
    result = None
    t = base + gauge.RELEASE_MS
    for _ in range(4 * 4):  # generous budget for a 4-LED sweep
        t += gauge._TRANSITION_STEP_MS
        result = g.step(("out", 0), t)
        if result == "unlocked":
            break

    assert result == "unlocked"
    assert len(strip.frames) > frames_before  # kept rendering throughout
    assert strip.frames[-1] == [(0, 0, 0)] * 4  # blanked on the way out
    # Back to display: an out-of-range sample resumes the LED effects (an in-range
    # one would immediately re-lock).
    assert g.step(("out", 0), t + 1) is None
    assert strip.frames[-1] == [(1, 2, 3)] * 4


class _FakeTof:
    """Minimal VL53L0X: a data_ready flag, a scripted read, and stop/start counts."""

    def __init__(self) -> None:
        """Start idle with no sample pending and no faults scripted."""
        self.data_ready = False
        self.raise_on_read = False
        self.reads = 0
        self.starts = 0
        self.stops = 0
        self._value = 0

    def set(self, mm: int) -> None:
        """Make one sample available, as the GPIO1 ISR would flag it."""
        self._value = mm
        self.data_ready = True

    def read(self) -> int:
        """Return the pending sample and clear the flag, or raise a scripted fault."""
        if self.raise_on_read:
            raise OSError("nack")
        self.reads += 1
        self.data_ready = False
        return self._value

    def stop(self) -> None:
        """Count a ranging stop (recovery)."""
        self.stops += 1

    def start(self) -> None:
        """Count a ranging start (recovery)."""
        self.starts += 1


class _FakeStrip:
    """Records each rendered frame as a plain list for assertions."""

    def __init__(self) -> None:
        """Start with no frames rendered."""
        self.frames: list = []

    def render(self, frame: list) -> None:
        """Store a copy of the rendered frame."""
        self.frames.append(list(frame))


class _FakeLed:
    """Stand-in LedState that always renders the same recognisable display frame."""

    def frame(self) -> list:
        """Return a constant 4-LED display frame."""
        return [(1, 2, 3)] * 4
