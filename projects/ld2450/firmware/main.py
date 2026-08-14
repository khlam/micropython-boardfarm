"""MicroPython firmware for HLK-LD2450 target telemetry.

The radar driver receives 256000-baud binary reports over UART. This project
converts each valid report to compact JSON on the independent USB-CDC console
consumed by the host dashboard.
"""

import os
import time
from collections import namedtuple
from math import atan2, degrees, sqrt

import ujson

from boot_status_led import status
from ld2450 import LD2450, DeviceNotFoundError

# Per-chip pin map — the authoritative wiring for this project, plain GPIO
# numbers. uart_id selects the UART peripheral the driver opens; tx drives
# the radar RX line, rx carries the report stream. Filled per chip by
# os.uname().machine dispatch at import.
Board = namedtuple("Board", ("name", "uart_id", "tx", "rx"))
_machine = os.uname().machine
if "ESP32S3" in _machine:
    BOARD = Board(name="ESP32-S3-Zero", uart_id=1, tx=17, rx=18)
elif "RP2350" in _machine:
    BOARD = Board(name="RP2350", uart_id=0, tx=0, rx=1)
else:
    BOARD = Board(name="RP2040-Zero", uart_id=1, tx=4, rx=5)

_BOOT_PAUSE_MS = 300
_RETRY_PAUSE_MS = 1_000
_READ_ERR_PAUSE_MS = 200


def emit(obj: dict) -> None:
    """Print one compact JSON object on the USB-CDC serial stream."""
    print(ujson.dumps(obj))


def init_sensor() -> LD2450:
    """Open and probe the radar UART, retrying until valid reports arrive.

    Returns:
        A live LD2450 driver with its first decoded report cached.
    """
    status.uart_init()
    while True:
        try:
            radar = LD2450(
                bus_id=BOARD.uart_id,
                tx=BOARD.tx,
                rx=BOARD.rx,
            )
        except DeviceNotFoundError as err:
            status.no_device()
            emit({"diag": "no_device", "err": str(err)})
            time.sleep_ms(_RETRY_PAUSE_MS)
        except OSError as err:
            status.init_err()
            emit({"diag": "init_err", "err": str(err)})
            time.sleep_ms(_RETRY_PAUSE_MS)
        else:
            emit({"diag": "radar_ok"})
            return radar


def stream(radar: LD2450) -> None:
    """Emit fresh target frames and recover from timeouts and UART faults."""
    timed_out = False
    status.streaming()
    while True:
        try:
            targets = radar.read_latest()
        except OSError as err:
            status.read_err()
            emit({"diag": "read_err", "err": str(err)})
            time.sleep_ms(_READ_ERR_PAUSE_MS)
            status.streaming()
            timed_out = False
            continue

        if targets is None:
            if not timed_out:
                status.read_err()
                emit({"diag": "frame_timeout", "t": time.ticks_ms()})
                timed_out = True
            continue

        if timed_out:
            status.streaming()
            timed_out = False
        emit({"t": time.ticks_ms(), "targets": [_target_dict(target) for target in targets]})


def main() -> None:
    """Run boot, initialize the radar, and stream."""
    status.boot()
    time.sleep_ms(_BOOT_PAUSE_MS)
    stream(init_sensor())


def _target_dict(target: object) -> dict:
    """Convert one immutable driver record to the project's JSON schema.

    Distance and bearing are derived here, on the MCU, so consumers get
    ready-to-plot polar values instead of recomputing them from x/y per frame.
    """
    return {
        "slot": target.slot,
        "x_mm": target.x_mm,
        "y_mm": target.y_mm,
        "speed_cm_s": target.speed_cm_s,
        "resolution_mm": target.resolution_mm,
        "distance_mm": round(sqrt(target.x_mm * target.x_mm + target.y_mm * target.y_mm)),
        "angle_deg": round(degrees(atan2(target.x_mm, target.y_mm))),
    }


main()
