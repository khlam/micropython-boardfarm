"""MCU-micropython firmware entry point for the led-effects WS2812B demo.

Cycles through four WS2812B animations — rainbow, hue rotation, breathing,
and colour fade — until a VL53L0X time-of-flight sensor detects an object held
steady above it. Holding an object at one distance for HOLD_MS collapses the
strip to a single LED whose position maps the measured distance onto the bar
(first LED = MIN_DISTANCE_MM, last LED = MAX_DISTANCE_MM); that LED then
live-tracks the object. Removing the object for RELEASE_MS plays a short
transition and resumes the animations.

The sensor is optional: if none is found at boot the animations still run and
the gesture is simply inactive. Pin assignments live in this module's BOARD
table (dispatched per chip by os.uname().machine); the project-local Strip
driver and the VL53L0X driver each take flat pins as constructor arguments, so
this firmware builds unchanged for RP2040, RP2350, and ESP32-S3.
"""

import os
import time
from collections import namedtuple

import ujson
from effects import Breathe, ColorFade, HueRotate, Rainbow
from strip import Strip

from boot_status_led import status
from vl53l0x import VL53L0X, DeviceNotFoundError

# Per-chip pin map — the authoritative wiring for this project, plain GPIO
# numbers. data_pin carries the external strip's data line, kept clear of the
# on-board WS2812 (boot status LED: GP16 on the Zeros, GPIO21 on ESP32-S3) so
# the on-board pixel is never first in the chain. sda/scl carry the VL53L0X
# soft-I²C bus (the driver opens it internally). Filled per chip by
# os.uname().machine dispatch at import.
Board = namedtuple("Board", ("name", "data_pin", "sda", "scl"))
_machine = os.uname().machine
if "ESP32S3" in _machine:
    BOARD = Board(name="ESP32-S3-Zero", data_pin=7, sda=1, scl=2)
elif "RP2350" in _machine:
    BOARD = Board(name="RP2350", data_pin=15, sda=0, scl=1)
else:
    BOARD = Board(name="RP2040-Zero", data_pin=15, sda=0, scl=1)

LED_COUNT = 20
FRAME_PERIOD_MS = 20  # ~50 fps render cadence when no sensor is pacing the loop
FRAMES_PER_EFFECT = 200  # frames shown before advancing to the next effect

# Distance gauge: readings are clamped to [MIN, MAX] and mapped linearly across
# the 20 LEDs. MAX_DISTANCE_MM is the tunable "max measurable distance" — the
# 20th LED. The VL53L0X reads reliably to ~1.2 m; 500 mm gives a short, precise
# close-range gauge.
MIN_DISTANCE_MM = 50
MAX_DISTANCE_MM = 500
OUT_OF_RANGE_MM = 8190  # sensor reports ~8190 mm (up to 65535) when nothing is in range

HOLD_TOLERANCE_MM = 25  # jitter band that still counts as "held at that distance"
HOLD_MS = 5000  # object must stay within tolerance this long to lock the gauge
RELEASE_MS = 5000  # object must stay out of range this long to leave the gauge

TIMING_BUDGET_US = 20_000  # ~50 Hz; read() self-paces the loop at this cadence
POSITION_COLOR = (0, 120, 255)  # colour of the single lit gauge LED

_BOOT_PAUSE_MS = 300
_TRANSITION_STEP_MS = 25  # per-LED dwell of the unlock sweep (~0.5 s total)
_INIT_ATTEMPTS = 3  # bounded sensor-init retries before degrading to no-sensor
_RETRY_PAUSE_MS = 500
_READ_ERR_PAUSE_MS = 200


def emit(obj: dict) -> None:
    """Print one line of compact JSON to the serial port.

    All firmware output must go through this helper; raw `print()` calls
    elsewhere pollute the serial stream and are silently dropped by the
    viz JSON parser.
    """
    print(ujson.dumps(obj))


def init_sensor() -> VL53L0X | None:
    """Bring up the VL53L0X, degrading to no-sensor if it never appears.

    The driver opens its own soft I²C bus from BOARD pins, scans, and
    soft-resets the chip. Unlike distance-stream this project is a display
    demo, so init is bounded: after `_INIT_ATTEMPTS` failures it gives up and
    returns None, letting the animations run without a sensor. Flags status
    LEDs along the way — no_device() when nothing ACKs at 0x29, init_err() when
    the device ACKs but driver init raises.

    Returns:
        An initialised VL53L0X in continuous-ranging mode, or None if no working
        sensor was found within `_INIT_ATTEMPTS`.
    """
    status.i2c_init()
    for _ in range(_INIT_ATTEMPTS):
        try:
            tof = VL53L0X(sda=BOARD.sda, scl=BOARD.scl)
            tof.set_measurement_timing_budget(TIMING_BUDGET_US)
            tof.start()
        except DeviceNotFoundError as err:
            status.no_device()
            emit({"diag": "no_device", "err": str(err)})
            time.sleep_ms(_RETRY_PAUSE_MS)
        except (OSError, RuntimeError) as err:
            # OSError = I²C NACK; RuntimeError = driver poll timeout.
            status.init_err()
            emit({"diag": "init_err", "err": str(err)})
            time.sleep_ms(_RETRY_PAUSE_MS)
        else:
            emit({"diag": "tof_ok", "addr": tof.address})
            return tof
    emit({"diag": "no_sensor"})
    return None


def read_distance(tof: VL53L0X | None) -> int | None:
    """Return the next in-range distance in mm, or None, pacing the loop.

    When a sensor is present, `tof.read()` blocks until the next sample is
    ready, so this call also paces the render loop at the timing budget. When
    no sensor is present it sleeps one frame period instead so the loop never
    spins. Out-of-range readings and transient faults both return None (the
    caller treats "no object" and "read failed" the same); a fault additionally
    flashes read_err and restarts continuous mode, mirroring distance-stream.

    Args:
        tof: The VL53L0X driver, or None when running without a sensor.

    Returns:
        Distance in mm for an in-range sample, else None.
    """
    if tof is None:
        time.sleep_ms(FRAME_PERIOD_MS)
        return None
    try:
        distance_mm = tof.read()
    except (OSError, RuntimeError) as err:
        status.read_err()
        emit({"diag": "read_err", "err": str(err)})
        try:
            tof.stop()
            tof.start()
        except (OSError, RuntimeError):
            pass
        time.sleep_ms(_READ_ERR_PAUSE_MS)
        status.streaming()
        return None
    if distance_mm >= OUT_OF_RANGE_MM:
        return None
    return distance_mm


def position_index(distance_mm: int) -> int:
    """Map a distance to a 0-based LED index, clamped to the gauge range.

    MIN_DISTANCE_MM maps to the first LED (0) and MAX_DISTANCE_MM to the last
    (LED_COUNT - 1); readings outside the range clamp to the nearest end.
    """
    span = MAX_DISTANCE_MM - MIN_DISTANCE_MM
    frac = (distance_mm - MIN_DISTANCE_MM) / span
    if frac < 0:
        frac = 0.0
    elif frac > 1:
        frac = 1.0
    return round(frac * (LED_COUNT - 1))


def position_frame(distance_mm: int) -> list:
    """Return a frame with only the gauge LED for `distance_mm` illuminated."""
    frame = [(0, 0, 0)] * LED_COUNT
    frame[position_index(distance_mm)] = POSITION_COLOR
    return frame


def play_transition(strip: Strip) -> None:
    """Sweep a single lit LED across the strip, then blank it (~0.5 s).

    Marks the return from the distance gauge to the cycling animations as a
    deliberate gesture rather than an abrupt cut.
    """
    for i in range(LED_COUNT):
        frame = [(0, 0, 0)] * LED_COUNT
        frame[i] = POSITION_COLOR
        strip.render(frame)
        time.sleep_ms(_TRANSITION_STEP_MS)
    strip.render([(0, 0, 0)] * LED_COUNT)


def build_effects() -> tuple:
    """Return the demo's four effects, each fully parametrised at the call site.

    Returns:
        ``(name, effect)`` pairs in display order; `name` is emitted as a
        diagnostic when the effect becomes active.
    """
    return (
        ("rainbow", Rainbow(LED_COUNT, brightness=0.3, step=0.01)),
        ("hue_rotate", HueRotate(LED_COUNT, brightness=0.3, speed=0.005)),
        ("breathe", Breathe(LED_COUNT, color=(0, 128, 255), brightness=0.4, period=80)),
        (
            "color_fade",
            ColorFade(LED_COUNT, start=(255, 0, 0), end=(0, 0, 255), brightness=0.3, step=0.01),
        ),
    )


def _step_unlocked(
    strip: Strip,
    effects: tuple,
    distance_mm: int | None,
    now: int,
    cycle: tuple,
    hold: tuple,
) -> tuple:
    """Advance one cycling frame: track the hold, then render or lock.

    A reading held within HOLD_TOLERANCE_MM for HOLD_MS locks the gauge; until
    then the current effect renders and advances after FRAMES_PER_EFFECT frames.

    Args:
        strip: The WS2812B strip driver.
        effects: ``(name, effect)`` pairs from build_effects().
        distance_mm: Latest in-range reading, or None.
        now: Current ``ticks_ms()`` timestamp.
        cycle: ``(effect_idx, frames_left)`` animation cursor.
        hold: ``(hold_candidate, hold_start)`` steady-hold tracker.

    Returns:
        ``(locked, cycle, hold)`` with the updated state; `locked` is True once
        the hold window elapses (no frame is rendered on the locking iteration).
    """
    effect_idx, frames_left = cycle
    hold_candidate, hold_start = hold
    if distance_mm is None:
        hold_candidate = None
    elif hold_candidate is None or abs(distance_mm - hold_candidate) > HOLD_TOLERANCE_MM:
        hold_candidate = distance_mm
        hold_start = now
    elif time.ticks_diff(now, hold_start) >= HOLD_MS:
        emit({"diag": "lock"})
        return True, cycle, (None, hold_start)
    strip.render(effects[effect_idx][1].frame())
    frames_left -= 1
    if frames_left <= 0:
        effect_idx = (effect_idx + 1) % len(effects)
        frames_left = FRAMES_PER_EFFECT
        emit({"effect": effects[effect_idx][0]})
    return False, (effect_idx, frames_left), (hold_candidate, hold_start)


def _step_locked(
    strip: Strip,
    distance_mm: int | None,
    now: int,
    release_start: int | None,
    gauge_frame: list | None,
) -> tuple:
    """Advance one gauge frame: track the object, or count down to release.

    While the object is in range the lit LED tracks it; once it is gone for
    RELEASE_MS the unlock transition plays.

    Args:
        strip: The WS2812B strip driver.
        distance_mm: Latest in-range reading, or None.
        now: Current ``ticks_ms()`` timestamp.
        release_start: When the object was first lost, or None.
        gauge_frame: Last rendered gauge frame, held while briefly out of range.

    Returns:
        ``(unlock, release_start, gauge_frame)`` with the updated state; `unlock`
        is True once the object has been gone for RELEASE_MS.
    """
    if distance_mm is not None:
        gauge_frame = position_frame(distance_mm)
        strip.render(gauge_frame)
        return False, None, gauge_frame
    if release_start is None:
        release_start = now
    elif time.ticks_diff(now, release_start) >= RELEASE_MS:
        play_transition(strip)
        return True, release_start, gauge_frame
    if gauge_frame is not None:
        strip.render(gauge_frame)
    return False, release_start, gauge_frame


def run(strip: Strip, tof: VL53L0X | None, effects: tuple) -> None:
    """Cycle animations, arming the distance gauge on a steady hold.

    Runs one flat loop paced by `read_distance`, dispatching each frame to
    `_step_unlocked` while cycling or `_step_locked` while the gauge is armed.
    Losing the object for RELEASE_MS resumes cycling from the same effect.

    Args:
        strip: The WS2812B strip driver.
        tof: The VL53L0X driver, or None to run animations without the gauge.
        effects: ``(name, effect)`` pairs from build_effects().
    """
    cycle = (0, FRAMES_PER_EFFECT)
    hold = (None, 0)
    locked = False
    release_start = None
    gauge_frame = None
    emit({"effect": effects[0][0]})
    while True:
        distance_mm = read_distance(tof)
        now = time.ticks_ms()
        if not locked:
            locked, cycle, hold = _step_unlocked(strip, effects, distance_mm, now, cycle, hold)
            if locked:
                release_start = None
                gauge_frame = None
        else:
            unlock, release_start, gauge_frame = _step_locked(
                strip, distance_mm, now, release_start, gauge_frame
            )
            if unlock:
                locked = False
                hold = (None, hold[1])
                cycle = (cycle[0], FRAMES_PER_EFFECT)
                emit({"diag": "unlock"})
                emit({"effect": effects[cycle[0]][0]})


def main() -> None:
    """Run boot → build strip + sensor → cycle. MicroPython entry point."""
    status.boot()
    time.sleep_ms(_BOOT_PAUSE_MS)
    strip = Strip(LED_COUNT, pin=BOARD.data_pin)
    tof = init_sensor()
    status.streaming()
    run(strip, tof, build_effects())


main()
