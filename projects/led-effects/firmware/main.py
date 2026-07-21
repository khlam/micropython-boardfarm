"""MCU firmware entry point for the led-effects WS2812B, OLED, and Wi-Fi demo.

Drives 20 WS2812B LEDs. In random mode it cycles four animations — rainbow, hue
rotation, breathing, and colour fade — choosing the next at each 200-frame
boundary; in solid mode it holds one configured colour. Bringing an object into
range of a VL53L0X time-of-flight sensor collapses the strip into a soft distance
gauge that live-tracks the object; one continuous second (RELEASE_MS) without an
object leaves the gauge and resumes the configured LED mode.

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
from gauge import Gauge, Sensor
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
# soft-I²C bus; int_pin is wired to the sensor's GPIO1 "new sample ready"
# output so reads are driven by a falling-edge interrupt instead of blocking;
# oled_sda/oled_scl give the SSD1306 a separate soft-I²C bus.
# Filled per chip by os.uname().machine dispatch at import.
Board = namedtuple("Board", ("name", "data_pin", "sda", "scl", "int_pin", "oled_sda", "oled_scl"))
_machine = os.uname().machine
if "ESP32S3" in _machine:
    BOARD = Board(name="ESP32-S3-Zero", data_pin=7, sda=1, scl=2, int_pin=3, oled_sda=8, oled_scl=9)
elif "RP2350" in _machine:
    BOARD = Board(name="RP2350", data_pin=15, sda=0, scl=1, int_pin=4, oled_sda=2, oled_scl=3)
else:
    BOARD = Board(name="RP2040-Zero", data_pin=15, sda=0, scl=1, int_pin=4, oled_sda=2, oled_scl=3)

LED_COUNT = 20
FRAME_PERIOD_MS = 20  # ~50 fps render cadence; run() holds every frame to this
FRAMES_PER_EFFECT = 200  # frames shown before choosing the next random effect

OLED_WIDTH = 128
OLED_HEIGHT = 64
OLED_ADDRESS = 0x3C

TIMING_BUDGET_US = 20_000  # ~50 Hz sensor cadence; each sample raises the INT

_TICK_MS = 10  # loop yield; polls sensor + provisioning, never spins (AGENTS: sleep >= 10 ms)
_BOOT_PAUSE_MS = 300
_INIT_ATTEMPTS = 3  # bounded sensor-init retries before degrading to no-sensor
_RETRY_PAUSE_MS = 500


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

    The driver opens its own soft I²C bus from BOARD pins, scans, soft-resets
    the chip, and wires its GPIO1 output to ``int_pin`` so ``Sensor`` can read
    on the falling-edge interrupt instead of blocking. Unlike distance-stream
    this project is a display demo, so init is bounded: after `_INIT_ATTEMPTS`
    failures it gives up and returns None, letting the animations run without a
    sensor. Flags status LEDs along the way — no_device() when nothing ACKs at
    0x29, init_err() when the device ACKs but driver init raises.

    Returns:
        An initialised VL53L0X in continuous-ranging mode, or None if no working
        sensor was found within `_INIT_ATTEMPTS`.
    """
    status.i2c_init()
    for _ in range(_INIT_ATTEMPTS):
        try:
            tof = VL53L0X(sda=BOARD.sda, scl=BOARD.scl, int_pin=BOARD.int_pin)
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
    """Event-driven loop: poll sensor + provisioning every tick, render at ~50 fps.

    A cooperative scheduler — one ``now`` per tick fanned out to three sub-services
    that each do bounded, non-blocking work: the interrupt-driven ``Sensor`` (reads
    only when GPIO1 has flagged a sample), the provisioning session (bounded HTTP/
    DNS), and the frame-gated renderer. Because nothing blocks, the gauge follows
    the object with no perceptible lag and a slow or timed-out read no longer stalls
    the strip. LED rendering is gated to FRAME_PERIOD_MS so the frame-count-driven
    effects and the glow easing keep their current ~50 fps look.

    The AP runs independently of the gauge; only the OLED is coupled to it. The QR
    is pre-rendered off-screen in the idle path (``provisioner.prerender``), so
    locking the gauge blits an already-built code and unlocking blanks the panel —
    each costing one I²C flush, never an in-frame encode.

    Args:
        strip: The WS2812B strip driver.
        tof: The VL53L0X driver, or None to run without the gauge.
        provisioner: The provisioning service, or None when unavailable.
        led_state: The LED display driver.
    """
    sensor = Sensor(tof, emit)
    gauge = Gauge(strip, led_state, LED_COUNT, emit)
    last_frame = time.ticks_ms()
    while True:
        now = time.ticks_ms()
        sample = sensor.poll(now)
        if provisioner is not None:
            provisioner.poll(now)
            provisioner.prerender()  # build the QR off-screen before it is shown
        if time.ticks_diff(now, last_frame) >= FRAME_PERIOD_MS:
            last_frame = now
            event = gauge.step(sample, now)
            if event == "locked":
                if provisioner is not None:
                    provisioner.show_qr()
            elif event == "unlocked":
                if provisioner is not None:
                    provisioner.hide_qr()
                emit({"diag": "unlock"})
        time.sleep_ms(_TICK_MS)


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
