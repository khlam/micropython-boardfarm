"""MCU-micropython firmware for multizone-ranging: I²C scan, VL53L5CX init, 8x8 JSON stream."""

import os
import time
from collections import namedtuple

import ujson

from boot_status_led import status
from i2c_bus import Wiring as I2cWiring
from i2c_bus import soft_i2c
from vl53l5cx import VL53L5CX

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

_TOF_ADDRESS = 0x29
# 8x8 hardware maximum. The VL53L5CX caps 8x8 ranging at 15 Hz; the read loop
# emits each grid as soon as the sensor flags it ready, so this sets the
# end-to-end frame rate. Soft I²C is required: the sensor clock-stretches
# heavily while loading its firmware in init(), which the hardware I²C
# peripheral aborts on (ETIMEDOUT / poll_for_answer failures during bootload).
_RANGING_FREQ_HZ = 15

# Long enough for the USB host to finish enumerating before init_sensor()
# begins the ~7-9 s VL53L5CX firmware upload. That upload is a run of ~370 ms
# blocking SoftI²C writes during which MicroPython can't service USB; if the
# host hasn't enumerated by the first blackout it gives up, and the device
# never re-attaches — the port is then dead until replug. Enumerating first
# makes those later blackouts harmless. (Observed on the RP2040-Zero; the
# RP2350/ESP32-S3 happen to win the race even at 50 ms, but the wait is
# harmless on every board so it stays chip-agnostic.)
_BOOT_PAUSE_MS = 1500
_RETRY_PAUSE_MS = 500
_READ_ERR_PAUSE_MS = 200
_POLL_INTERVAL_MS = 10


def emit(obj: dict) -> None:
    """Serialize obj to compact JSON on stdout."""
    print(ujson.dumps(obj))


def init_sensor(i2c: object) -> VL53L5CX:
    """Scan the I²C bus and initialise the VL53L5CX, retrying until it comes up.

    Loads ~86.5 KB of ST firmware into the sensor over soft I²C (~7-9 s at 100 kHz).
    Parks at status.no_device() when 0x29 is absent, or status.init_err() when
    the device ACKs but driver init raises.

    Args:
        i2c: An open I²C bus (from i2c_bus.soft_i2c) exposing scan().

    Returns:
        An initialised VL53L5CX driver in 8x8 ranging mode.
    """
    status.i2c_init()
    while True:
        try:
            devices = i2c.scan()
            emit({"diag": "scan", "devices": devices})
            if _TOF_ADDRESS not in devices:
                status.no_device()
                emit({"diag": "no_device", "devices": devices})
                time.sleep_ms(_RETRY_PAUSE_MS)
                continue
            tof = VL53L5CX(i2c)
            emit({"diag": "firmware_loading"})
            tof.init()
            tof.start(_RANGING_FREQ_HZ)
            emit({"diag": "vl53l5cx_ok", "addr": _TOF_ADDRESS})
        except (OSError, RuntimeError, ValueError) as err:
            status.init_err()
            emit({"diag": "init_err", "err": str(err)})
            time.sleep_ms(_RETRY_PAUSE_MS)
        else:
            return tof


def stream(tof: VL53L5CX) -> None:
    """Stream 8x8 distance grids indefinitely, polling for new data.

    Emits one JSON line per measurement: {"t": <ms>, "grid": [<64 int|null>]}.
    Each grid element is an integer distance in mm, or null for zones with an
    invalid or out-of-range target_status.
    """
    status.streaming()
    while True:
        try:
            if not tof.check_data_ready():
                time.sleep_ms(_POLL_INTERVAL_MS)
                continue
            grid = tof.read()
            emit({"t": time.ticks_ms(), "grid": grid})
        except (OSError, RuntimeError, ValueError) as err:
            status.read_err()
            emit({"diag": "read_err", "err": str(err)})
            try:
                tof.stop()
                tof.start(_RANGING_FREQ_HZ)
            except (OSError, RuntimeError, ValueError):
                pass
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
