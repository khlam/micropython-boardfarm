"""MCU-micropython firmware entry point for compass QMC5883P telemetry.

Initialises the LED state machine, scans the I²C bus for a QMC5883P
magnetometer at its fixed address 0x2C, then streams raw X/Y/Z field counts
plus a computed heading as one-JSON-per-line on the serial port at ~50 Hz.

Chip-agnostic: all hardware-specific behaviour lives in the package backends
(boot_status_led, i2c_bus, qmc5883p).
"""

import math
import time

import ujson

from boot_status_led import status
from i2c_bus import hard_i2c as i2c
from qmc5883p import QMC5883P

# QMC5883P fixed I²C address (not configurable on this part).
MAG_ADDRESS = 0x2C

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


def init_sensor() -> QMC5883P:
    """Scan the bus and initialise the QMC5883P, retrying until it comes up.

    Parks at status.no_device() when nothing responds at 0x2C, and at
    status.init_err() when the device ACKs but the chip-ID check or a config
    write raises. Both states retry every _RETRY_PAUSE_MS.
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
    """Stream heading + raw field samples until the system halts.

    read() blocks until the next sample is ready (~20 ms at 50 Hz), so the loop
    is self-paced with no extra sleep. Edge-triggers a {"diag": "ovl"} on the
    rising edge of the STATUS overflow bit so a sustained saturation event
    doesn't flood the stream.
    """
    ovl_prev = False
    status.streaming()
    while True:
        try:
            x, y, z = mag.read()
            heading = (math.degrees(math.atan2(y, x)) + 360) % 360
            emit(
                {
                    "t": time.ticks_ms(),
                    "x": x,
                    "y": y,
                    "z": z,
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
    mag = init_sensor()
    stream(mag)


main()
