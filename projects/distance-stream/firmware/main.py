"""MCU-micropython firmware for distance-stream: I²C scan, VL53L0X init, JSON stream."""

import os
import time
from collections import namedtuple

import ujson

from boot_status_led import status
from smoothing import median
from vl53l0x import VL53L0X, DeviceNotFoundError

# Per-chip pin map — the authoritative wiring for this project, plain GPIO
# numbers. The VL53L0X opens a bit-banged soft I²C bus internally, so no
# peripheral id is needed. Filled per chip by os.uname().machine dispatch.
Board = namedtuple("Board", ("name", "sda", "scl"))
_machine = os.uname().machine
if "ESP32S3" in _machine:
    BOARD = Board(name="ESP32-S3-Zero", sda=1, scl=2)
elif "RP2350" in _machine:
    BOARD = Board(name="RP2350", sda=0, scl=1)
else:
    BOARD = Board(name="RP2040-Zero", sda=0, scl=1)

# Sensor reports ~8190 mm (and up to 65535) when nothing is in range;
# emit null so the viz shows a gap instead of a spurious large value.
OUT_OF_RANGE_MM = 8190

# Rolling median over the last SMOOTH_WINDOW in-range samples rejects spikes
# while smoothing jitter. The window resets on out-of-range and read errors
# so it never bridges across a gap.
SMOOTH_WINDOW = 10

# 20 ms budget → ~50 Hz; the moving average compensates for the higher
# per-sample noise vs 40 ms.
TIMING_BUDGET_US = 20_000

_BOOT_PAUSE_MS = 50
_RETRY_PAUSE_MS = 500
_READ_ERR_PAUSE_MS = 200


def emit(obj: dict) -> None:
    """Serialize obj to compact JSON on stdout."""
    print(ujson.dumps(obj))


def init_sensor() -> VL53L0X:
    """Open the bus and initialise the VL53L0X, retrying until it comes up.

    The driver opens its own soft I²C bus from BOARD pins, scans, and soft-resets
    the chip. Parks at status.no_device() when no device is present at 0x29
    (DeviceNotFoundError), and at status.init_err() when the device ACKs but driver
    init raises.

    Returns:
        An initialised VL53L0X driver in continuous-ranging mode.
    """
    status.i2c_init()
    while True:
        try:
            tof = VL53L0X(sda=BOARD.sda, scl=BOARD.scl)
            tof.set_measurement_timing_budget(TIMING_BUDGET_US)
            tof.start()
            emit({"diag": "tof_ok", "addr": tof.address})
        except DeviceNotFoundError as e:
            status.no_device()
            emit({"diag": "no_device", "err": str(e)})
            time.sleep_ms(_RETRY_PAUSE_MS)
        except (OSError, RuntimeError) as err:
            # OSError = I²C NACK; RuntimeError = driver poll timeout.
            status.init_err()
            emit({"diag": "init_err", "err": str(err)})
            time.sleep_ms(_RETRY_PAUSE_MS)
        else:
            return tof


def stream(tof: VL53L0X) -> None:
    """Stream raw and smoothed distance samples indefinitely.

    Each in-range record carries both the raw reading (`distance_mm_raw`) and
    its rolling median (`distance_mm`, equal to the raw reading until the window
    fills). read() blocks until the next sample is ready, so the loop is
    self-paced at the configured timing budget with no extra sleep.
    """
    window: list[int] = []
    status.streaming()
    while True:
        try:
            distance_mm = tof.read()
            if distance_mm >= OUT_OF_RANGE_MM:
                del window[:]
                emit({"t": time.ticks_ms(), "distance_mm": None, "distance_mm_raw": None})
            else:
                window.append(distance_mm)
                if len(window) > SMOOTH_WINDOW:
                    del window[0]
                smoothed = median(window, SMOOTH_WINDOW)
                emit(
                    {
                        "t": time.ticks_ms(),
                        "distance_mm": round(smoothed),
                        "distance_mm_raw": distance_mm,
                    }
                )
        except (OSError, RuntimeError) as err:
            # Transient fault; restart continuous mode before resuming.
            status.read_err()
            emit({"diag": "read_err", "err": str(err)})
            try:
                tof.stop()
                tof.start()
            except (OSError, RuntimeError):
                pass
            del window[:]
            time.sleep_ms(_READ_ERR_PAUSE_MS)
            status.streaming()


def main() -> None:
    """Run boot → init → stream."""
    status.boot()
    time.sleep_ms(_BOOT_PAUSE_MS)
    tof = init_sensor()
    stream(tof)


main()
