"""MCU-micropython firmware entry point for gyro-stream MPU6050 telemetry.

Initialises the LED state machine, scans the I²C bus for an MPU6050 at
0x68 (or 0x69 if AD0 is tied to 3V3), then streams accel + gyro + temp
samples as one-JSON-per-line on the serial port at ~100 Hz.

Pin assignments live in this module's BOARD table (dispatched per chip by
os.uname().machine); chip-specific *behaviour* — including which I²C bus the
sensor opens and its 0x68/0x69 address probe — stays in the packages
(boot_status_led, mpu6050).
"""

import os
import time
from collections import namedtuple

import ujson

from boot_status_led import status
from mpu6050 import MPU6050, DeviceNotFoundError

# Per-chip pin map — the authoritative wiring for this project, plain GPIO
# numbers. i2c_id selects the hardware I²C peripheral the driver opens. Filled
# per chip by os.uname().machine dispatch at import.
Board = namedtuple("Board", ("name", "i2c_id", "sda", "scl"))
_machine = os.uname().machine
if "ESP32S3" in _machine:
    BOARD = Board(name="ESP32-S3-Zero", i2c_id=0, sda=1, scl=2)
elif "RP2350" in _machine:
    BOARD = Board(name="RP2350", i2c_id=0, sda=0, scl=1)
else:
    BOARD = Board(name="RP2040-Zero", i2c_id=0, sda=0, scl=1)

# ~100 Hz polling. The MPU6050 is poll-driven (no INT line wired), so
# the loop sets the cadence via sleep_ms — distance-stream's self-paced
# `tof.read()` pattern doesn't apply here.
SAMPLE_PERIOD_MS = 10

# Boot/init pacing.
_BOOT_PAUSE_MS = 300
_RETRY_PAUSE_MS = 500
_READ_ERR_PAUSE_MS = 200


def emit(obj: dict) -> None:
    """Print one line of compact JSON to the serial port.

    All firmware output must go through this helper; raw `print()` calls
    elsewhere pollute the serial stream and are silently dropped by the
    viz JSON parser.
    """
    print(ujson.dumps(obj))


def init_sensor() -> MPU6050:
    """Open the bus and initialise the MPU6050, retrying until it comes up.

    The driver opens its own bus from BOARD pins and auto-detects the address
    (0x68 with AD0=GND/floating, else 0x69). Parks at status.no_device() when
    neither address responds (DeviceNotFoundError), and at status.init_err() when
    WHO_AM_I or a config write raises. Both states retry every _RETRY_PAUSE_MS.

    Returns:
        An initialised MPU6050 driver bound to the bus it opened.
    """
    status.i2c_init()
    while True:
        try:
            imu = MPU6050(bus_id=BOARD.i2c_id, sda=BOARD.sda, scl=BOARD.scl)
            emit({"diag": "imu_ok", "addr": imu.addr, "kind": imu.kind})
        except DeviceNotFoundError as e:
            # Bus reachable but no device responded at 0x68/0x69.
            # Check SDA/SCL wiring, 3V3 power, GND, pull-ups.
            status.no_device()
            emit({"diag": "no_device", "err": str(e)})
            time.sleep_ms(_RETRY_PAUSE_MS)
        except OSError as e:
            # Device ACKed at 0x68/0x69 but WHO_AM_I or a config write
            # failed. Likely a counterfeit chip or a bus glitch.
            status.init_err()
            emit({"diag": "init_err", "err": str(e)})
            time.sleep_ms(_RETRY_PAUSE_MS)
        else:
            return imu


def stream(imu: MPU6050) -> None:
    """Stream IMU samples at ~100 Hz until the system halts.

    Emits one sample dict per iteration. Edge-triggers a {"diag": "sat"}
    on the rising edge of imu.last_saturated so a sustained over-range
    event doesn't flood the stream.
    """
    sat_prev = False
    status.streaming()
    while True:
        try:
            ax, ay, az, gx, gy, gz, tc = imu.read_all()
            emit(
                {
                    "t": time.ticks_ms(),
                    "ax": ax,
                    "ay": ay,
                    "az": az,
                    "gx": gx,
                    "gy": gy,
                    "gz": gz,
                    "T": tc,
                }
            )
            sat = imu.last_saturated
            if sat and not sat_prev:
                emit({"diag": "sat"})
            sat_prev = sat
        except OSError as e:
            # Transient I²C fault. Surface once, settle, then resume.
            status.read_err()
            emit({"diag": "read_err", "err": str(e)})
            time.sleep_ms(_READ_ERR_PAUSE_MS)
            status.streaming()
            continue
        time.sleep_ms(SAMPLE_PERIOD_MS)


def main() -> None:
    """Run boot → init → stream. MicroPython entry point."""
    status.boot()
    time.sleep_ms(_BOOT_PAUSE_MS)
    imu = init_sensor()
    stream(imu)


main()
