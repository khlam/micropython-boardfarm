"""Event-driven distance sensing and the LED distance-gauge state machine.

Split out of ``main.py`` so the non-blocking sensing and gauge logic can be
unit-tested on the host without booting the firmware. Both classes take their
side-effecting dependencies (``emit`` for JSON diagnostics, the strip and LED
display) by injection, so a test drives them with fakes.

- ``Sensor`` turns the interrupt-driven VL53L0X into a non-blocking source of
  classified distance samples: it reads only when GPIO1 has flagged a fresh
  sample and recovers from faults/stalls on a ticks deadline, never sleeping.
- ``Gauge`` is the display → locked → transition state machine, stepped once per
  rendered frame, that shows the LED effects and collapses to a live glow as soon
  as an object comes into range of the sensor.
"""

import utime

from boot_status_led import status

# Distance gauge: readings are clamped to [MIN, MAX] and mapped linearly across
# the strip. MAX_DISTANCE_MM is the tunable "max measurable distance" — the last
# LED. The VL53L0X reads reliably to ~1.2 m; 500 mm gives a short, precise
# close-range gauge.
MIN_DISTANCE_MM = 50
MAX_DISTANCE_MM = 500
OUT_OF_RANGE_MM = 8190  # sensor reports ~8190 mm (up to 65535) when nothing is in range

RELEASE_MS = 1000  # object must stay confirmed out of range this long to leave the gauge

POSITION_COLOR = (0, 120, 255)  # base colour of the gauge glow
GLOW_RADIUS = 2.5  # half-width in LEDs of the glow's linear brightness falloff
POSITION_SMOOTHING = 0.25  # per-frame easing fraction toward the target position (0-1)

_TRANSITION_STEP_MS = 25  # per-LED dwell of the unlock sweep (~0.5 s total)
_SENSOR_STALL_MS = 300  # no fresh sample this long ⇒ a missed INT edge; re-arm ranging
_READ_ERR_PAUSE_MS = 200


class Sensor:
    """Interrupt-driven, non-blocking source of classified distance samples.

    ``poll`` reads the VL53L0X only when its GPIO1 falling-edge ISR has flagged
    a fresh sample (``tof.data_ready``), so a poll never blocks on the sensor.
    It caches the last classification and returns it between samples. A read
    fault, or a stalled interrupt (no fresh sample within ``_SENSOR_STALL_MS``,
    which wedges when a missed edge leaves GPIO1 asserted), schedules a
    deadline-based ``stop()``/``start()`` recovery — the pause is measured with
    ``ticks_diff``, never slept — so the render loop keeps running throughout.

    Samples are classified into the three cases the gauge treats differently:
    an in-range object, a confirmed out-of-range reading, and a sensor error
    (or no sensor). Only confirmed out-of-range samples advance the release
    timer; errors preserve the gauge's current state.
    """

    def __init__(self, tof, emit) -> None:  # noqa: ANN001
        """Wrap a VL53L0X (or None for a permanent error), emitting via ``emit``."""
        self._tof = tof
        self._emit = emit
        self._sample = ("err", 0)
        self._last_ready_ms = utime.ticks_ms()
        self._recovering = False
        self._recover_start = 0

    def poll(self, now: int) -> tuple:
        """Return the latest classified sample without blocking.

        Args:
            now: Current ``ticks_ms()`` timestamp, shared with the loop.

        Returns:
            ``("in", mm)`` for an in-range reading, ``("out", 0)`` for a
            confirmed out-of-range reading, or ``("err", 0)`` for a fault, an
            in-progress recovery, or a missing sensor.
        """
        if self._tof is None:
            return ("err", 0)
        if self._recovering:
            return self._recover(now)
        try:
            if self._tof.data_ready:
                self._sample = _classify(self._tof.read())
                self._last_ready_ms = now
            elif utime.ticks_diff(now, self._last_ready_ms) >= _SENSOR_STALL_MS:
                self._begin_recovery(now, "sensor_stall")
        except (OSError, RuntimeError) as err:
            # OSError = I²C NACK; RuntimeError = driver poll timeout.
            self._begin_recovery(now, "read_err", err)
        return self._sample

    def _begin_recovery(self, now: int, reason: str, err: object = None) -> None:
        """Flash read_err, report, and arm the non-blocking recovery deadline."""
        status.read_err()
        diag = {"diag": reason}
        if err is not None:
            diag["err"] = str(err)
        self._emit(diag)
        self._sample = ("err", 0)
        self._recovering = True
        self._recover_start = now

    def _recover(self, now: int) -> tuple:
        """Wait out ``_READ_ERR_PAUSE_MS``, then restart continuous ranging once."""
        if utime.ticks_diff(now, self._recover_start) < _READ_ERR_PAUSE_MS:
            return self._sample
        try:
            self._tof.stop()
            self._tof.start()
        except (OSError, RuntimeError):
            pass
        self._recovering = False
        self._last_ready_ms = now
        status.streaming()
        return self._sample


class Gauge:
    """Distance-gauge state machine, stepped once per rendered frame.

    Runs ``display → locked → transition`` entirely from ``ticks`` deadlines, so
    no step blocks — the unlock sweep is spread across frames rather than slept
    through. ``step`` renders exactly one frame and returns a transition event the
    loop reacts to:

    - ``display``: shows the LED effects; the first in-range reading locks the
      gauge immediately (returns ``"locked"``). Out-of-range and error samples
      keep the effects on screen.
    - ``locked``: eases a glow a ``POSITION_SMOOTHING`` fraction toward the
      ranged object each frame; a confirmed out-of-range reading for
      ``RELEASE_MS`` starts the release sweep. Errors preserve glow and timer.
    - ``transition``: sweeps the glow across the strip one LED per
      ``_TRANSITION_STEP_MS``, then blanks and returns to ``display`` (returns
      ``"unlocked"``).
    """

    def __init__(self, strip, led_state, led_count, emit) -> None:  # noqa: ANN001
        """Start in the display state driving ``led_state`` onto ``strip``."""
        self._strip = strip
        self._led = led_state
        self._count = led_count
        self._emit = emit
        self._state = "display"
        self._position = None
        self._release_start = None
        self._sweep_i = 0
        self._sweep_start = 0

    def step(self, sample: tuple, now: int) -> str | None:
        """Advance and render one frame; return ``"locked"``/``"unlocked"`` or None.

        Args:
            sample: ``Sensor.poll`` result — ``("in", mm)``/``("out", 0)``/``("err", 0)``.
            now: Current ``ticks_ms()`` timestamp.

        Returns:
            ``"locked"`` when the gauge just locked, ``"unlocked"`` when the
            release sweep just finished, or ``None`` on an ordinary frame.
        """
        if self._state == "display":
            return self._step_display(sample)
        if self._state == "transition":
            return self._step_transition(now)
        return self._step_locked(sample, now)

    def _step_display(self, sample: tuple) -> str | None:
        """Lock the gauge as soon as an object is in range, else render the display."""
        if sample[0] == "in":
            self._emit({"diag": "lock"})
            self._state = "locked"
            self._position = None
            self._release_start = None
            return "locked"
        # An out-of-range or error sample keeps the LED effects on screen.
        self._strip.render(self._led.frame())
        return None

    def _step_locked(self, sample: tuple, now: int) -> str | None:
        """Ease the glow toward the object, or count down toward release."""
        kind, mm = sample
        if kind == "in":
            target = position_fraction(mm, self._count)
            if self._position is None:
                self._position = target
            else:
                self._position += (target - self._position) * POSITION_SMOOTHING
            self._release_start = None
            self._strip.render(gauge_frame(self._position, self._count))
            return None
        if kind == "out":
            if self._release_start is None:
                self._release_start = now
            elif utime.ticks_diff(now, self._release_start) >= RELEASE_MS:
                self._state = "transition"
                self._sweep_i = 0
                self._sweep_start = now
                return None
            if self._position is not None:
                self._strip.render(gauge_frame(self._position, self._count))
            return None
        # kind == "err": preserve state; keep the current glow, do not count down.
        if self._position is not None:
            self._strip.render(gauge_frame(self._position, self._count))
        return None

    def _step_transition(self, now: int) -> str | None:
        """Sweep the glow one LED at a time, then blank and return to display."""
        if self._sweep_i >= self._count:
            self._strip.render([(0, 0, 0)] * self._count)
            self._state = "display"
            self._position = None
            self._release_start = None
            return "unlocked"
        self._strip.render(gauge_frame(self._sweep_i, self._count))
        if utime.ticks_diff(now, self._sweep_start) >= _TRANSITION_STEP_MS:
            self._sweep_i += 1
            self._sweep_start = now
        return None


def position_fraction(distance_mm: int, count: int) -> float:
    """Map a distance to a fractional LED position, clamped to the gauge range.

    MIN_DISTANCE_MM maps to the first LED (0.0) and MAX_DISTANCE_MM to the last
    (count - 1); readings outside the range clamp to the nearest end. The result
    is fractional so the glow can sit between LEDs and slide smoothly across them
    rather than snapping to whole-pixel positions.
    """
    span = MAX_DISTANCE_MM - MIN_DISTANCE_MM
    frac = (distance_mm - MIN_DISTANCE_MM) / span
    if frac < 0:
        frac = 0.0
    elif frac > 1:
        frac = 1.0
    return frac * (count - 1)


def gauge_frame(position: float, count: int) -> list:
    """Render a soft glow centred on fractional LED `position` across `count` LEDs.

    Each LED's brightness falls off linearly with its distance from `position`
    over GLOW_RADIUS LEDs, so the lit spot spans its neighbours and moving the
    centre a fraction of a pixel cross-fades the light between them.
    """
    frame = []
    for i in range(count):
        offset = abs(i - position)
        if offset >= GLOW_RADIUS:
            frame.append((0, 0, 0))
        else:
            frame.append(_dim(POSITION_COLOR, 1 - offset / GLOW_RADIUS))
    return frame


def _classify(distance_mm: int) -> tuple:
    """Bucket a raw distance into the gauge's ``in``/``out`` sample tuple."""
    if distance_mm >= OUT_OF_RANGE_MM:
        return ("out", 0)
    return ("in", distance_mm)


def _dim(rgb: tuple, factor: float) -> tuple:
    """Scale each channel of `rgb` by `factor` (0.0-1.0)."""
    return (int(rgb[0] * factor), int(rgb[1] * factor), int(rgb[2] * factor))
