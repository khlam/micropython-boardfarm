"""MCU-micropython firmware entry point for compass QMC5883P telemetry.

Initialises the LED state machine, scans the I²C bus for a QMC5883P
magnetometer at its fixed address 0x2C, then streams raw X/Y/Z field counts,
their smoothed counterparts (xs/ys/zs), and a computed heading as
one-JSON-per-line on the serial port at ~50 Hz.

Pin assignments live in this module's BOARD table (dispatched per chip by
os.uname().machine); chip-specific *behaviour* stays in the packages
(boot_status_led, i2c_bus, qmc5883p).
"""

import math
import os
import time
from collections import namedtuple

import ujson

from boot_status_led import status
from i2c_bus import Wiring as I2cWiring
from i2c_bus import hard_i2c
from qmc5883p import QMC5883P
from smoothing import simple_moving_average

# Per-chip pin map — the authoritative wiring for this project. i2c.id selects
# the hardware I²C peripheral; sda/scl are GPIO numbers. Filled per chip by
# os.uname().machine dispatch at import.
Board = namedtuple("Board", ("name", "i2c"))
_machine = os.uname().machine
if "ESP32S3" in _machine:
    BOARD = Board(name="ESP32-S3-Zero", i2c=I2cWiring(id=0, sda=1, scl=2))
elif "RP2350" in _machine:
    BOARD = Board(name="RP2350", i2c=I2cWiring(id=0, sda=0, scl=1))
else:
    BOARD = Board(name="RP2040-Zero", i2c=I2cWiring(id=0, sda=0, scl=1))

# QMC5883P fixed I²C address (not configurable on this part).
MAG_ADDRESS = 0x2C

# Per-axis simple moving average; each smoothed value equals the raw reading
# until its window fills with SMOOTH_WINDOW samples.
SMOOTH_WINDOW = 10

# STATUS bit1 — field saturation (usually a magnet too close).
_OVL_MASK = 0x02

# Boot/init pacing.
_BOOT_PAUSE_MS = 300
_RETRY_PAUSE_MS = 500
_READ_ERR_PAUSE_MS = 200


def emit(obj: dict) -> None:
    """Print one line of compact JSON to the serial port.

    All firmware output must go through this helper; raw `print()` calls
    elsewhere pollute the serial stream and are silently dropped by the viz
    JSON parser.
    """
    print(ujson.dumps(obj))


def init_sensor(i2c: object) -> QMC5883P:
    """Scan the bus and initialise the QMC5883P, retrying until it comes up.

    Parks at status.no_device() when nothing responds at 0x2C, and at
    status.init_err() when the device ACKs but the chip-ID check or a config
    write raises. Both states retry every _RETRY_PAUSE_MS.

    Args:
        i2c: An open I²C bus (from i2c_bus.hard_i2c) exposing scan().

    Returns:
        An initialised QMC5883P driver bound to the bus.
    """
    status.i2c_init()
    while True:
        try:
            devices = i2c.scan()
            emit({"diag": "scan", "devices": devices})
            if MAG_ADDRESS not in devices:
                # Bus reachable but no device responded.
                # Check SDA/SCL wiring, 3V3 power, GND, pull-ups.
                status.no_device()
                emit({"diag": "no_device", "devices": devices})
                time.sleep_ms(_RETRY_PAUSE_MS)
                continue
            mag = QMC5883P(i2c)
            emit({"diag": "mag_ok", "addr": mag.address})
        except OSError as e:
            # Device ACKed at 0x2C but the chip-ID check or a config write
            # failed. Likely a wrong sensor on the bus or a bus glitch.
            status.init_err()
            emit({"diag": "init_err", "err": str(e)})
            time.sleep_ms(_RETRY_PAUSE_MS)
        else:
            return mag


def stream(mag: QMC5883P) -> None:
    """Stream heading + raw and smoothed field samples until the system halts.

    Each record carries the raw x/y/z counts and their per-axis moving averages
    xs/ys/zs (equal to the raw reading until each window fills). The heading is
    computed from the smoothed field so the needle is steady. read() blocks
    until the next sample is ready (~20 ms at 50 Hz), so the loop is self-paced
    with no extra sleep. Edge-triggers a {"diag": "ovl"} on the rising edge of
    the STATUS overflow bit so a sustained saturation event doesn't flood the
    stream.
    """
    xs_buf: list[int] = []
    ys_buf: list[int] = []
    zs_buf: list[int] = []
    ovl_prev = False
    status.streaming()
    while True:
        try:
            x, y, z = mag.read()
            xs_buf.append(x)
            ys_buf.append(y)
            zs_buf.append(z)
            if len(xs_buf) > SMOOTH_WINDOW:
                del xs_buf[0]
                del ys_buf[0]
                del zs_buf[0]
            xs = simple_moving_average(xs_buf, SMOOTH_WINDOW)
            ys = simple_moving_average(ys_buf, SMOOTH_WINDOW)
            zs = simple_moving_average(zs_buf, SMOOTH_WINDOW)
            # Heading is driven by the smoothed field so the needle doesn't
            # jitter; xs/ys equal the raw reading until the window fills.
            heading = (math.degrees(math.atan2(ys, xs)) + 360) % 360
            emit(
                {
                    "t": time.ticks_ms(),
                    "x": x,
                    "y": y,
                    "z": z,
                    "xs": xs,
                    "ys": ys,
                    "zs": zs,
                    "heading_deg": round(heading, 1),
                }
            )
            ovl = bool(mag.last_status & _OVL_MASK)
            if ovl and not ovl_prev:
                emit({"diag": "ovl"})
            ovl_prev = ovl
        except OSError as e:
            # Transient I²C fault. The sensor stays in continuous mode, so just
            # surface it once, settle, and resume — no re-init dance needed.
            status.read_err()
            emit({"diag": "read_err", "err": str(e)})
            time.sleep_ms(_READ_ERR_PAUSE_MS)
            status.streaming()
            continue


def main() -> None:
    """Run boot → init → stream. MicroPython entry point."""
    status.boot()
    time.sleep_ms(_BOOT_PAUSE_MS)
    i2c = hard_i2c(BOARD.i2c)
    mag = init_sensor(i2c)
    stream(mag)


main()
