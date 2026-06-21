"""MCU-micropython firmware for distance-stream: I²C scan, VL53L0X init, JSON stream."""

import os
import time
from collections import namedtuple

import ujson

from boot_status_led import status
from i2c_bus import Wiring as I2cWiring
from i2c_bus import soft_i2c
from smoothing import median
from vl53l0x import VL53L0X

# Per-chip pin map — the authoritative wiring for this project. Soft I²C is
# bit-banged so i2c.id is unused; sda/scl are GPIO numbers. Filled per chip by
# os.uname().machine dispatch at import.
Board = namedtuple("Board", ("name", "i2c"))
_machine = os.uname().machine
if "ESP32S3" in _machine:
    BOARD = Board(name="ESP32-S3-Zero", i2c=I2cWiring(id=0, sda=1, scl=2))
elif "RP2350" in _machine:
    BOARD = Board(name="RP2350", i2c=I2cWiring(id=0, sda=0, scl=1))
else:
    BOARD = Board(name="RP2040-Zero", i2c=I2cWiring(id=0, sda=0, scl=1))

TOF_ADDRESS = 0x29

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
_SOFT_RESET_PAUSE_MS = 2
_SOFT_RESET_POLLS = 50

_REG_SOFT_RESET = 0xBF
_REG_MODEL_ID = 0xC0
_MODEL_ID_BOOTED = 0xEE


def emit(obj: dict) -> None:
    """Serialize obj to compact JSON on stdout."""
    print(ujson.dumps(obj))


def soft_reset_sensor(bus: object, address: int = TOF_ADDRESS) -> bool:
    """Soft-reset the VL53L0X and poll until it reboots.

    Clears any half-init state from a previous attempt before the
    driver touches calibration registers.

    Args:
        bus: Object exposing writeto_mem / readfrom_mem.
        address: 7-bit I²C address of the sensor.

    Returns:
        True if the chip signals ready within the poll budget, False otherwise.
    """
    try:
        bus.writeto_mem(address, _REG_SOFT_RESET, b"\x00")
        time.sleep_ms(_SOFT_RESET_PAUSE_MS)
        bus.writeto_mem(address, _REG_SOFT_RESET, b"\x01")
        time.sleep_ms(_SOFT_RESET_PAUSE_MS)
        for _ in range(_SOFT_RESET_POLLS):
            if bus.readfrom_mem(address, _REG_MODEL_ID, 1)[0] == _MODEL_ID_BOOTED:
                return True
            time.sleep_ms(_SOFT_RESET_PAUSE_MS)
    except OSError:
        return False
    return False


def init_sensor(i2c: object) -> VL53L0X:
    """Scan i2c bus and initialise VL53L0X, retrying until it comes up.

    Parks at status.no_device() when no device is present at 0x29, and at
    status.init_err() when the device ACKs but driver init raises.

    Args:
        i2c: An open I²C bus (from i2c_bus.soft_i2c) exposing scan() and the
            writeto_mem/readfrom_mem the soft reset uses.

    Returns:
        An initialised VL53L0X driver in continuous-ranging mode.
    """
    status.i2c_init()
    while True:
        try:
            devices = i2c.scan()
            emit({"diag": "scan", "devices": devices})
            if TOF_ADDRESS not in devices:
                status.no_device()
                emit({"diag": "no_device", "devices": devices})
                time.sleep_ms(_RETRY_PAUSE_MS)
                continue
            # This breakout variant signals ranging done via bit 6 of
            # _RESULT_INTERRUPT_STATUS and hangs in the SPAD-info procedure;
            # both quirks apply on all MCUs, not just ESP32 or RP.
            soft_reset_sensor(i2c)
            tof = VL53L0X(i2c, skip_spad_info=True, interrupt_status_mask=0xFF)
            tof.set_measurement_timing_budget(TIMING_BUDGET_US)
            tof.start()
            emit({"diag": "tof_ok", "addr": tof.address})
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
    i2c = soft_i2c(BOARD.i2c)
    tof = init_sensor(i2c)
    stream(tof)


main()
