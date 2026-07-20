"""MCU firmware entry point for the led-effects WS2812B, OLED, and Wi-Fi demo.

Drives 20 WS2812B LEDs. In random mode it cycles four animations — rainbow, hue
rotation, breathing, and colour fade — choosing the next at each 200-frame
boundary; in solid mode it holds one configured colour. Holding an object steady
above a VL53L0X time-of-flight sensor for HOLD_MS collapses the strip into a soft
distance gauge that live-tracks the object; one continuous second (RELEASE_MS)
without an object leaves the gauge and resumes the configured LED mode.

Separately and continuously from boot, the device runs a locked-down WPA2 access
point whose credentials rotate every ten minutes. Anyone who can join it can set
the LED colour or mode from a tiny no-JavaScript page. Those credentials are only
ever shown as a QR code on the 128x64 SSD1306 OLED, and only while the distance
gauge is engaged; the panel is blank at every other moment. The AP itself keeps
running either way — the gauge gates who can *read* the credentials, not who may
keep using ones already read. Pin assignments live in this module's BOARD table
(dispatched per chip by os.uname().machine); the same firmware builds for RP2040
(no Wi-Fi — provisioning is an inert no-op), RP2350/Pico 2 W, and ESP32-S3.
"""

import os
import time
from collections import namedtuple

import settings
import ujson
from effects import Breathe, ColorFade, HueRotate, Rainbow
from provisioning import PROV_CONFIG, Provisioner, hex_to_rgb
from ssd1306 import SSD1306
from ssd1306 import DeviceNotFoundError as OledNotFoundError
from strip import Strip

import wifi
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
FRAMES_PER_EFFECT = 200  # frames shown before choosing the next random effect

OLED_WIDTH = 128
OLED_HEIGHT = 64
OLED_ADDRESS = 0x3C

# Distance gauge: readings are clamped to [MIN, MAX] and mapped linearly across
# the 20 LEDs. MAX_DISTANCE_MM is the tunable "max measurable distance" — the
# 20th LED. The VL53L0X reads reliably to ~1.2 m; 500 mm gives a short, precise
# close-range gauge.
MIN_DISTANCE_MM = 50
MAX_DISTANCE_MM = 500
OUT_OF_RANGE_MM = 8190  # sensor reports ~8190 mm (up to 65535) when nothing is in range

HOLD_TOLERANCE_MM = 25  # jitter band that still counts as "held at that distance"
HOLD_MS = 1000  # object must stay within tolerance this long to lock the gauge
RELEASE_MS = 1000  # object must stay confirmed out of range this long to leave the gauge

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
    viz JSON parser. Never emit a credential, QR payload, or CSRF token.
    """
    print(ujson.dumps(obj))


class LedState:
    """Drives the non-gauge LED display: random effect cycling or a solid colour.

    Holds the persisted LED mode. In random mode it renders the current effect
    and, at each FRAMES_PER_EFFECT boundary, picks one of the four effects with
    ``os.urandom(1)``; in solid mode it renders one fixed colour. The gauge does
    not use this — on gauge exit the loop simply resumes calling ``frame()``.
    """

    def __init__(self, effects: tuple) -> None:
        """Start in random mode with the supplied effects."""
        self._effects = effects
        self._mode = "random"
        self._color = (0, 0, 0)
        self._effect_idx = 0
        self._frames_left = FRAMES_PER_EFFECT

    def apply(self, record: dict) -> None:
        """Adopt a persisted settings record (from settings.load/save)."""
        self._mode = record["mode"]
        if self._mode == "solid":
            self._color = hex_to_rgb(record["color"])
        emit({"diag": "led_mode", "mode": self._mode})

    def frame(self) -> list:
        """Return the next frame for the current mode."""
        if self._mode == "solid":
            return [self._color] * LED_COUNT
        frame = self._effects[self._effect_idx][1].frame()
        self._frames_left -= 1
        if self._frames_left <= 0:
            self._effect_idx = os.urandom(1)[0] % len(self._effects)
            self._frames_left = FRAMES_PER_EFFECT
            emit({"effect": self._effects[self._effect_idx][0]})
        return frame


def init_display() -> SSD1306 | None:
    """Initialise the OLED and leave it blank, its resting state.

    The display uses the dedicated OLED software-I²C pins in ``BOARD``. Blank is
    where this panel spends most of its life: the provisioning QR is the only
    thing the project ever draws, and only while the distance gauge is engaged, so
    a startup message would linger as the one persistent thing on screen and read
    as status it cannot back up. Missing or faulty display hardware is optional:
    after bounded retries this function emits ``oled_disabled`` and returns None so
    the LED effects and distance sensor can still start. A working OLED is required
    to provision.

    Returns:
        The initialised, blanked SSD1306, or None after all attempts fail.
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


def read_sample(tof: VL53L0X | None) -> tuple:
    """Classify the latest sensor reading for the gauge state machine.

    Distinguishes three cases so the gauge can treat them differently: an
    in-range object, a confirmed out-of-range reading, and a sensor error (or no
    sensor). Only confirmed out-of-range samples should advance the gauge-release
    timer; errors must preserve the current state. A fault flashes read_err and
    restarts continuous mode, mirroring distance-stream.

    Args:
        tof: The VL53L0X driver, or None when running without a sensor.

    Returns:
        ``("in", mm)`` for an in-range reading, ``("out", 0)`` for a confirmed
        out-of-range reading, or ``("err", 0)`` for a fault or missing sensor.
    """
    if tof is None:
        return ("err", 0)
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
        return ("err", 0)
    if distance_mm >= OUT_OF_RANGE_MM:
        return ("out", 0)
    return ("in", distance_mm)


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

    Marks the return from the distance gauge to the LED display as a deliberate
    gesture rather than an abrupt cut.
    """
    for i in range(LED_COUNT):
        strip.render(gauge_frame(i))
        time.sleep_ms(_TRANSITION_STEP_MS)
    strip.render([(0, 0, 0)] * LED_COUNT)


def build_effects() -> tuple:
    """Return the demo's four effects, each fully parametrised at the call site.

    Returns:
        ``(name, effect)`` pairs; `name` is emitted as a diagnostic when the
        effect becomes active in random mode.
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
    led_state: LedState,
    sample: tuple,
    now: int,
    hold: tuple,
) -> tuple:
    """Advance one display frame: track the hold, then render or lock.

    A reading held within HOLD_TOLERANCE_MM for HOLD_MS locks the gauge. A
    confirmed out-of-range sample resets the hold; a sensor error preserves it.

    Args:
        strip: The WS2812B strip driver.
        led_state: The LED display driver (random cycling or solid colour).
        sample: ``read_sample`` result.
        now: Current ``ticks_ms()`` timestamp.
        hold: ``(hold_candidate, hold_start)`` steady-hold tracker.

    Returns:
        ``(locked, hold)`` with the updated state; `locked` is True once the hold
        window elapses (no frame is rendered on the locking iteration).
    """
    kind, mm = sample
    hold_candidate, hold_start = hold
    if kind == "in":
        if hold_candidate is None or abs(mm - hold_candidate) > HOLD_TOLERANCE_MM:
            hold_candidate = mm
            hold_start = now
        elif time.ticks_diff(now, hold_start) >= HOLD_MS:
            emit({"diag": "lock"})
            return True, (None, hold_start)
    elif kind == "out":
        hold_candidate = None
    # kind == "err": preserve the hold tracker unchanged.
    strip.render(led_state.frame())
    return False, (hold_candidate, hold_start)


def _step_locked(
    strip: Strip,
    sample: tuple,
    now: int,
    release_start: int | None,
    position: float | None,
) -> tuple:
    """Advance one gauge frame: ease the glow toward the object, or count down.

    While the object is in range the glow eases a POSITION_SMOOTHING fraction of
    the way toward its mapped position each frame. Only a confirmed out-of-range
    sample advances the RELEASE_MS release timer; a sensor error preserves the
    current glow and timer. The first in-range reading snaps the glow to its
    position.

    Args:
        strip: The WS2812B strip driver.
        sample: ``read_sample`` result.
        now: Current ``ticks_ms()`` timestamp.
        release_start: When the object was first confirmed gone, or None.
        position: Eased fractional LED position of the glow, or None before the
            first in-range reading.

    Returns:
        ``(unlock, release_start, position)`` with the updated state; `unlock`
        is True once the object has been confirmed gone for RELEASE_MS.
    """
    kind, mm = sample
    if kind == "in":
        target = position_fraction(mm)
        if position is None:
            position = target
        else:
            position += (target - position) * POSITION_SMOOTHING
        strip.render(gauge_frame(position))
        return False, None, position
    if kind == "out":
        if release_start is None:
            release_start = now
        elif time.ticks_diff(now, release_start) >= RELEASE_MS:
            play_transition(strip)
            return True, release_start, position
        if position is not None:
            strip.render(gauge_frame(position))
        return False, release_start, position
    # kind == "err": preserve state; keep the current glow, do not count down.
    if position is not None:
        strip.render(gauge_frame(position))
    return False, release_start, position


def setup_provisioning(display: SSD1306 | None, led_state: LedState) -> Provisioner | None:
    """Bring provisioning up as a background service, or disable it for the boot.

    Requires a working OLED — the QR is the only way credentials are ever shown —
    then calls ``wifi.quiesce()`` once to clear any stale AP and checks the port
    supports an AP at all. Every failure, including an unexpected one, is
    reported and swallowed: provisioning is skipped for the boot and the caller
    keeps running effects and the gauge.

    Args:
        display: The OLED the QR is drawn on, or None if it never came up.
        led_state: Shared LED state the provisioner drives while the portal runs.

    Returns:
        A started ``Provisioner`` (whose ``poll`` is a no-op if setup later
        disabled it), or None when provisioning is unavailable this boot.
    """
    if display is None:
        emit({"diag": "wifi_no_oled"})
        return None
    try:
        wifi.quiesce()
        if not wifi.capabilities()["supported"]:
            emit({"diag": "wifi_unsupported"})
            return None
        provisioner = Provisioner(PROV_CONFIG, display, led_state, emit)
    except wifi.ProvisioningError as err:
        emit({"diag": "wifi_disabled", "code": err.code})
        return None
    except Exception as err:  # noqa: BLE001 - never let setup stop the LEDs
        emit({"diag": "wifi_fail", "err": type(err).__name__})
        return None
    provisioner.begin()  # contains its own failures; leaves itself disabled
    return provisioner


def run(
    strip: Strip,
    tof: VL53L0X | None,
    provisioner: Provisioner | None,
    led_state: LedState,
) -> None:
    """Render the display, arm the gauge on a steady hold, and poll provisioning.

    One flat loop paced to FRAME_PERIOD_MS. Each iteration samples the sensor,
    polls the provisioning session (bounded, nonblocking), then renders either
    the LED display (``_step_unlocked``) or the distance gauge (``_step_locked``).
    The AP runs independently of the gauge; only the OLED is coupled to it — the
    QR is drawn when the gauge locks and the panel blanked when it releases, so
    the two transitions each cost one frame's worth of I²C flush.

    Args:
        strip: The WS2812B strip driver.
        tof: The VL53L0X driver, or None to run without the gauge.
        provisioner: The provisioning service, or None when unavailable.
        led_state: The LED display driver.
    """
    hold = (None, 0)
    locked = False
    release_start = None
    position = None
    while True:
        frame_start = time.ticks_ms()
        sample = read_sample(tof)
        now = time.ticks_ms()
        if provisioner is not None:
            provisioner.poll(now)
        if not locked:
            locked, hold = _step_unlocked(strip, led_state, sample, now, hold)
            if locked:
                release_start = None
                position = None
                if provisioner is not None:
                    provisioner.show_qr()
        else:
            unlock, release_start, position = _step_locked(
                strip, sample, now, release_start, position
            )
            if unlock:
                locked = False
                hold = (None, hold[1])
                if provisioner is not None:
                    provisioner.hide_qr()
                emit({"diag": "unlock"})
        # Hold each iteration to the fixed frame period so the display runs at
        # ~50 fps regardless of sensor timing; a longer iteration (transition,
        # a one-off provisioning transition) leaves the remainder negative and
        # skips the sleep. Never spins: the body is near-instant otherwise.
        elapsed = time.ticks_diff(time.ticks_ms(), frame_start)
        if elapsed < FRAME_PERIOD_MS:
            time.sleep_ms(FRAME_PERIOD_MS - elapsed)


def _dim(rgb: tuple, factor: float) -> tuple:
    """Scale each channel of `rgb` by `factor` (0.0-1.0)."""
    return (int(rgb[0] * factor), int(rgb[1] * factor), int(rgb[2] * factor))


def main() -> None:
    """Run boot → build display, strip, sensor, and provisioning → render."""
    status.boot()
    time.sleep_ms(_BOOT_PAUSE_MS)
    strip = Strip(LED_COUNT, pin=BOARD.data_pin)
    display = init_display()
    tof = init_sensor()
    led_state = LedState(build_effects())
    led_state.apply(settings.load())
    provisioner = setup_provisioning(display, led_state)
    status.streaming()
    run(strip, tof, provisioner, led_state)


main()
