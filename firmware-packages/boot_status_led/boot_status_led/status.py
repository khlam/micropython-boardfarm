"""MCU-micropython state machine for the board-agnostic LED status indicator.

Sets LED colour for different firmware states.

Public API:
    status.boot()       # white  — firmware running, before I/O
    status.i2c_init()   # cyan   — I²C bus configured, scanning for device(s)
    status.no_device()  # orange — bus reachable, device(s) not present
    status.init_err()   # magenta — device(s) ACKed but driver init raised
    status.streaming()  # green  — device(s) live, samples flowing
    status.read_err()   # red    — transient fault during streaming
"""

import os

# Pick the chip-specific backend at import time
_machine = os.uname().machine
if "ESP32S3" in _machine:
    # Module is named esp32s3 (not esp32) because MicroPython's ESP32 port
    # ships a built-in C module called `esp32` that would shadow our frozen
    # one — `from esp32 import show` would resolve to the built-in and
    # AttributeError on `show`, killing boot before status.boot() runs.
    from boot_status_led.esp32s3 import show as _show
elif "RP2350" in _machine:
    from boot_status_led.rp2350 import show as _show
else:
    from boot_status_led.rp2040 import show as _show

# Named state colours. RP2040 path uses the full RGB
# RP2350 backend treats anything that isn't pure green as "off"
BOOT = (255, 255, 255)
I2C_INIT = (0, 255, 255)
NO_DEVICE = (255, 128, 0)
INIT_ERR = (255, 0, 255)
STREAMING = (0, 255, 0)
READ_ERR = (255, 0, 0)


def boot() -> None:
    """Signal firmware running, before I/O (white)."""
    _show(BOOT)


def i2c_init() -> None:
    """Signal I²C bus configured, scanning for sensor (cyan)."""
    _show(I2C_INIT)


def no_device() -> None:
    """Signal bus reachable, device not present (orange)."""
    _show(NO_DEVICE)


def init_err() -> None:
    """Signal sensor ACKed but driver init raised (magenta)."""
    _show(INIT_ERR)


def streaming() -> None:
    """Signal sensor live, samples flowing (green)."""
    _show(STREAMING)


def read_err() -> None:
    """Signal transient I²C fault during streaming (red)."""
    _show(READ_ERR)
