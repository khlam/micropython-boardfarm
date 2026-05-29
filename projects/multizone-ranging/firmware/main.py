"""MCU-micropython firmware for multizone-ranging: I²C scan, VL53L5CX init, 8×8 JSON stream."""

import time

import ujson

from boot_status_led import status
from i2c_bus import soft_i2c as i2c
from vl53l5cx import VL53L5CX

_TOF_ADDRESS = 0x29
_RANGING_FREQ_HZ = 10

_BOOT_PAUSE_MS = 50
_RETRY_PAUSE_MS = 500
_READ_ERR_PAUSE_MS = 200
_POLL_INTERVAL_MS = 10


def emit(obj: dict) -> None:
    """Serialize obj to compact JSON on stdout."""
    print(ujson.dumps(obj))


def init_sensor() -> VL53L5CX:
    """Scan the I²C bus and initialise the VL53L5CX, retrying until it comes up.

    Loads ~86.5 KB of ST firmware into the sensor over I²C (~2-3 s at 400 kHz).
    Parks at status.no_device() when 0x29 is absent, or status.init_err() when
    the device ACKs but driver init raises.
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
    """Stream 8×8 distance grids indefinitely, polling for new data.

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
    tof = init_sensor()
    stream(tof)


main()
