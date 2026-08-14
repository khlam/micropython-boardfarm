"""RP2040-Zero firmware for HLK-LD2450 target telemetry.

The radar driver receives 256000-baud binary reports on UART1. This project
converts each valid report to compact JSON on the independent USB-CDC console
consumed by the host dashboard.
"""

import os
import time
from collections import namedtuple

import ujson

from boot_status_led import status
from ld2450 import LD2450, DeviceNotFoundError

Board = namedtuple("Board", ("name", "uart_id", "tx", "rx"))
_machine = os.uname().machine
if "RP2040" in _machine and "RP2350" not in _machine:
    BOARD = Board(name="RP2040-Zero", uart_id=1, tx=4, rx=5)
else:
    BOARD = None

_BOOT_PAUSE_MS = 300
_RETRY_PAUSE_MS = 1_000
_READ_ERR_PAUSE_MS = 200
_UNSUPPORTED_PAUSE_MS = 1_000


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
        except (OSError, ValueError) as err:
            status.init_err()
            emit({"diag": "init_err", "err": str(err)})
            time.sleep_ms(_RETRY_PAUSE_MS)
        else:
            emit({"diag": "radar_ok"})
            return radar


def stream(radar: LD2450) -> None:
    """Emit every valid target frame and recover from timeouts and UART faults."""
    timed_out = False
    status.streaming()
    while True:
        try:
            targets = radar.read()
        except OSError as err:
            status.read_err()
            emit({"diag": "read_err", "err": str(err)})
            time.sleep_ms(_READ_ERR_PAUSE_MS)
            status.streaming()
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
    """Run boot, validate the supported MCU, initialize the radar, and stream."""
    status.boot()
    time.sleep_ms(_BOOT_PAUSE_MS)
    if BOARD is None:
        emit({"diag": "unsupported_mcu", "machine": _machine})
        while True:
            time.sleep_ms(_UNSUPPORTED_PAUSE_MS)
    radar = init_sensor()
    stream(radar)


def _target_dict(target: object) -> dict:
    """Convert one immutable driver record to the project's JSON schema."""
    return {
        "slot": target.slot,
        "x_mm": target.x_mm,
        "y_mm": target.y_mm,
        "speed_cm_s": target.speed_cm_s,
        "resolution_mm": target.resolution_mm,
    }


main()
