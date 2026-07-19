"""MCU firmware entry point for the led-effects WS2812B and OLED demo.

Cycles through four WS2812B animations — rainbow, hue rotation, breathing,
and colour fade — until a VL53L0X time-of-flight sensor detects an object held
steady above it. Holding an object at one distance for HOLD_MS collapses the
strip to a soft glow whose position maps the measured distance onto the bar
(first LED = MIN_DISTANCE_MM, last LED = MAX_DISTANCE_MM); the glow then
live-tracks the object, easing smoothly between LEDs as the distance changes.
Removing the object for RELEASE_MS plays a short transition and resumes the
animations.

At startup a 128x64 SSD1306 OLED displays ``Hello world``. The display and
sensor use separate software-I²C pin pairs and are optional: if either is absent,
the animations still run and only that peripheral's feature is inactive. Pin
assignments live in this module's BOARD table (dispatched per chip by
os.uname().machine); drivers take flat pins as constructor arguments, so this
firmware builds unchanged for RP2040, RP2350, and ESP32-S3.
"""

import os
import time
from collections import namedtuple

import ujson
from effects import Breathe, ColorFade, HueRotate, Rainbow
from ssd1306 import SSD1306
from ssd1306 import DeviceNotFoundError as OledNotFoundError
from strip import Strip

from boot_status_led import status
from vl53l0x import VL53L0X, DeviceNotFoundError

# Per-chip pin map — the authoritative wiring for this project, plain GPIO
# numbers. data_pin carries the external strip's data line, kept clear of the
# on-board WS2812 (boot status LED: GP16 on the Zeros, GPIO21 on ESP32-S3) so
# the on-board pixel is never first in the chain. sda/scl carry the VL53L0X
# soft-I²C bus; oled_sda/oled_scl give the SSD1306 a separate soft-I²C bus.
# Filled per chip by os.uname().machine dispatch at import.
Board = namedtuple("Board", ("name", "data_pin", "sda", "scl", "oled_sda", "oled_scl"))
_machine = os.uname().machine
if "ESP32S3" in _machine:
    BOARD = Board(name="ESP32-S3-Zero", data_pin=7, sda=1, scl=2, oled_sda=8, oled_scl=9)
elif "RP2350" in _machine:
    BOARD = Board(name="RP2350", data_pin=15, sda=0, scl=1, oled_sda=2, oled_scl=3)
else:
    BOARD = Board(name="RP2040-Zero", data_pin=15, sda=0, scl=1, oled_sda=2, oled_scl=3)

LED_COUNT = 20
FRAME_PERIOD_MS = 20  # ~50 fps render cadence; run() holds every frame to this
FRAMES_PER_EFFECT = 200  # frames shown before advancing to the next effect

OLED_WIDTH = 128
OLED_HEIGHT = 64
OLED_ADDRESS = 0x3C
OLED_MESSAGE = "Hello world"

# Distance gauge: readings are clamped to [MIN, MAX] and mapped linearly across
# the 20 LEDs. MAX_DISTANCE_MM is the tunable "max measurable distance" — the
# 20th LED. The VL53L0X reads reliably to ~1.2 m; 500 mm gives a short, precise
# close-range gauge.
MIN_DISTANCE_MM = 50
MAX_DISTANCE_MM = 500
OUT_OF_RANGE_MM = 8190  # sensor reports ~8190 mm (up to 65535) when nothing is in range

HOLD_TOLERANCE_MM = 25  # jitter band that still counts as "held at that distance"
HOLD_MS = 1000  # object must stay within tolerance this long to lock the gauge
RELEASE_MS = 5000  # object must stay out of range this long to leave the gauge

TIMING_BUDGET_US = 20_000  # ~50 Hz; read() self-paces the loop at this cadence
POSITION_COLOR = (0, 120, 255)  # base colour of the gauge glow
GLOW_RADIUS = 2.5  # half-width in LEDs of the glow's linear brightness falloff
POSITION_SMOOTHING = 0.25  # per-frame easing fraction toward the target position (0-1)

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


def init_display() -> SSD1306 | None:
    """Initialise the OLED and show the startup message when it is present.

    The display uses the dedicated OLED software-I²C pins in ``BOARD``. Missing
    or faulty display hardware is optional: after bounded retries this function
    emits ``oled_disabled`` and returns None so the LED effects and distance
    sensor can still start.

    Returns:
        The initialised SSD1306 displaying ``Hello world``, or None after all
        attempts fail.
    """
    status.i2c_init()
    for _ in range(_INIT_ATTEMPTS):
        try:
            display = SSD1306(
                sda=BOARD.oled_sda,
                scl=BOARD.oled_scl,
                width=OLED_WIDTH,
                height=OLED_HEIGHT,
                address=OLED_ADDRESS,
            )
            display.fill(0)
            display.text(OLED_MESSAGE, 0, 0, 1)
            display.show()
        except OledNotFoundError as err:
            status.no_device()
            emit({"diag": "no_oled", "err": str(err)})
            time.sleep_ms(_RETRY_PAUSE_MS)
        except (OSError, RuntimeError) as err:
            status.init_err()
            emit({"diag": "oled_init_err", "err": str(err)})
            time.sleep_ms(_RETRY_PAUSE_MS)
        else:
            emit({"diag": "oled_ok", "addr": display.address})
            return display
    emit({"diag": "oled_disabled"})
    return None


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
    """Return the next in-range distance in mm, or None.

    A single reading for the gesture tracker: `tof.read()` returns the latest
    sample and returns None with no sensor attached. This no longer paces the
    loop — `run()` holds each iteration to FRAME_PERIOD_MS so the animation
    keeps main's fixed ~50 fps cadence no matter how fast the sensor samples.
    Out-of-range readings and transient faults both return None (the caller
    treats "no object" and "read failed" the same); a fault additionally
    flashes read_err and restarts continuous mode, mirroring distance-stream.

    Args:
        tof: The VL53L0X driver, or None when running without a sensor.

    Returns:
        Distance in mm for an in-range sample, else None.
    """
    if tof is None:
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


def position_fraction(distance_mm: int) -> float:
    """Map a distance to a fractional LED position, clamped to the gauge range.

    MIN_DISTANCE_MM maps to the first LED (0.0) and MAX_DISTANCE_MM to the last
    (LED_COUNT - 1); readings outside the range clamp to the nearest end. The
    result is fractional so the glow can sit between LEDs and slide smoothly
    across them rather than snapping to whole-pixel positions.
    """
    span = MAX_DISTANCE_MM - MIN_DISTANCE_MM
    frac = (distance_mm - MIN_DISTANCE_MM) / span
    if frac < 0:
        frac = 0.0
    elif frac > 1:
        frac = 1.0
    return frac * (LED_COUNT - 1)


def gauge_frame(position: float) -> list:
    """Render a soft glow centred on fractional LED `position`.

    Each LED's brightness falls off linearly with its distance from `position`
    over GLOW_RADIUS LEDs, so the lit spot spans its neighbours and moving the
    centre a fraction of a pixel cross-fades the light between them.
    """
    frame = []
    for i in range(LED_COUNT):
        offset = abs(i - position)
        if offset >= GLOW_RADIUS:
            frame.append((0, 0, 0))
        else:
            frame.append(_dim(POSITION_COLOR, 1 - offset / GLOW_RADIUS))
    return frame


def play_transition(strip: Strip) -> None:
    """Sweep the gauge glow across the strip, then blank it (~0.5 s).

    Marks the return from the distance gauge to the cycling animations as a
    deliberate gesture rather than an abrupt cut.
    """
    for i in range(LED_COUNT):
        strip.render(gauge_frame(i))
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
    position: float | None,
) -> tuple:
    """Advance one gauge frame: ease the glow toward the object, or count down.

    While the object is in range the glow eases a POSITION_SMOOTHING fraction of
    the way toward its mapped position each frame, so distance changes cross-fade
    smoothly across the strip instead of jumping; once the object is gone for
    RELEASE_MS the unlock transition plays. The first in-range reading snaps the
    glow straight to its position so it appears where the object is.

    Args:
        strip: The WS2812B strip driver.
        distance_mm: Latest in-range reading, or None.
        now: Current ``ticks_ms()`` timestamp.
        release_start: When the object was first lost, or None.
        position: Eased fractional LED position of the glow, or None before the
            first in-range reading. Held while briefly out of range.

    Returns:
        ``(unlock, release_start, position)`` with the updated state; `unlock`
        is True once the object has been gone for RELEASE_MS.
    """
    if distance_mm is not None:
        target = position_fraction(distance_mm)
        if position is None:
            position = target
        else:
            position += (target - position) * POSITION_SMOOTHING
        strip.render(gauge_frame(position))
        return False, None, position
    if release_start is None:
        release_start = now
    elif time.ticks_diff(now, release_start) >= RELEASE_MS:
        play_transition(strip)
        return True, release_start, position
    if position is not None:
        strip.render(gauge_frame(position))
    return False, release_start, position


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
    position = None
    emit({"effect": effects[0][0]})
    while True:
        frame_start = time.ticks_ms()
        distance_mm = read_distance(tof)
        now = time.ticks_ms()
        if not locked:
            locked, cycle, hold = _step_unlocked(strip, effects, distance_mm, now, cycle, hold)
            if locked:
                release_start = None
                position = None
        else:
            unlock, release_start, position = _step_locked(
                strip, distance_mm, now, release_start, position
            )
            if unlock:
                locked = False
                hold = (None, hold[1])
                cycle = (cycle[0], FRAMES_PER_EFFECT)
                emit({"diag": "unlock"})
                emit({"effect": effects[cycle[0]][0]})
        # Hold each iteration to the fixed frame period so the animation runs at
        # main's ~50 fps regardless of how fast tof.read() returns; a longer
        # iteration (e.g. play_transition) leaves the remainder negative and
        # skips the sleep. Never spins: with no sensor the body is near-instant
        # and this sleep paces the whole loop.
        elapsed = time.ticks_diff(time.ticks_ms(), frame_start)
        if elapsed < FRAME_PERIOD_MS:
            time.sleep_ms(FRAME_PERIOD_MS - elapsed)


def _dim(rgb: tuple, factor: float) -> tuple:
    """Scale each channel of `rgb` by `factor` (0.0-1.0)."""
    return (int(rgb[0] * factor), int(rgb[1] * factor), int(rgb[2] * factor))


def main() -> None:
    """Run boot → build display, strip, and sensor → cycle."""
    status.boot()
    time.sleep_ms(_BOOT_PAUSE_MS)
    strip = Strip(LED_COUNT, pin=BOARD.data_pin)
    _display = init_display()
    tof = init_sensor()
    status.streaming()
    run(strip, tof, build_effects())


main()
