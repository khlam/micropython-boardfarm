"""Send current HLK-LD2450 targets over the board's USB serial connection.

The radar driver wakes this asyncio application when UART data becomes idle.
This firmware turns the newest complete report into one compact JSON object
for the live dashboard.
"""

import asyncio
import os
import time
from collections import namedtuple
from math import atan2, degrees, sqrt

import ujson

from boot_status_led import status
from ld2450 import LD2450, DeviceNotFoundError

# This table is the wiring used by each supported board. ``uart_id`` selects a
# UART, ``tx`` connects to radar RX, and ``rx`` connects to radar TX.
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
    """Send one compact JSON object over the board's USB serial connection."""
    print(ujson.dumps(obj))


async def init_sensor() -> LD2450:
    """Connect to the radar, retrying until it sends a valid report.

    Returns:
        A connected radar driver with its first report ready to read.
    """
    status.uart_init()
    while True:
        try:
            radar = LD2450(
                bus_id=BOARD.uart_id,
                tx=BOARD.tx,
                rx=BOARD.rx,
            )
            await radar.wait_ready()
        except DeviceNotFoundError as err:
            status.no_device()
            emit({"diag": "no_device", "err": str(err)})
            await asyncio.sleep_ms(_RETRY_PAUSE_MS)
        except OSError as err:
            status.init_err()
            emit({"diag": "init_err", "err": str(err)})
            await asyncio.sleep_ms(_RETRY_PAUSE_MS)
        else:
            emit({"diag": "radar_ok"})
            return radar


async def stream(radar: LD2450) -> None:
    """Send the newest targets and recover from missing reports or UART errors."""
    timed_out = False
    status.streaming()
    while True:
        try:
            targets = await radar.read_latest()
        except OSError as err:
            status.read_err()
            emit({"diag": "read_err", "err": str(err)})
            await asyncio.sleep_ms(_READ_ERR_PAUSE_MS)
            status.streaming()
            timed_out = False
            continue

        if targets is None:
            if not timed_out:
                status.read_err()
                emit({"diag": "report_timeout", "t": time.ticks_ms()})
                timed_out = True
            continue

        if timed_out:
            status.streaming()
            timed_out = False
        emit({"t": time.ticks_ms(), "targets": [_target_dict(target) for target in targets]})


async def main() -> None:
    """Run boot, initialize the radar, and stream."""
    status.boot()
    await asyncio.sleep_ms(_BOOT_PAUSE_MS)
    radar = await init_sensor()
    try:
        await stream(radar)
    finally:
        radar.close()


def _target_dict(target: object) -> dict:
    """Convert one target to the JSON fields used by the dashboard.

    Distance and angle are calculated here so every display uses the same
    values.
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


asyncio.run(main())
