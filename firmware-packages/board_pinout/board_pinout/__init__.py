"""Board pin topology — the single source of truth for each board's wiring.

Projects read ``BOARD`` and pass pins explicitly into each package's
``connect()``; packages no longer claim pins at import time. The structure
separates shared buses (``SpiBus`` / ``I2cBus`` / ``UartBus`` — only the lines a
bus shares) from device attachments (``Device`` — which bus a peripheral hangs
off plus its device-specific ``cs`` / ``addr``), so several devices can share one
bus. It carries no read-scheduling, so it stays agnostic to a project's control
loop: independent buses sit on disjoint pins and may be pumped concurrently in
whatever loop/scheduler a project chooses.

``BOARD`` is chip-dispatched at import time via ``os.uname().machine``. The
namedtuple types are defined above the dispatch so the per-board backends
(``rp2040_zero`` / ``rp2350`` / ``esp32s3_zero``) can import them while this
module is still initialising. The package README holds the authoritative pin
tables that ``tests/test_board_pinout.py`` enforces against these instances.
"""

import os
from collections import namedtuple

SpiBus = namedtuple("SpiBus", ("id", "sck", "mosi", "miso"))
I2cBus = namedtuple("I2cBus", ("id", "sda", "scl"))
UartBus = namedtuple("UartBus", ("id", "tx", "rx"))
Device = namedtuple("Device", ("bus", "cs", "addr"))  # cs: SPI; addr: I2C; None when N/A
Board = namedtuple("Board", ("name", "status_led", "spi", "i2c", "uart", "devices"))

# RP2040-Zero underside solder pads — banned from signal use unless a board file
# overrides with an explicit, commented justification (see README "Pin ban").
RP2040_ZERO_BANNED = (17, 18, 19)

_machine = os.uname().machine
if "ESP32S3" in _machine:
    from board_pinout.esp32s3_zero import BOARD
elif "RP2350" in _machine:
    from board_pinout.rp2350 import BOARD
else:
    from board_pinout.rp2040_zero import BOARD

__all__ = [
    "BOARD",
    "RP2040_ZERO_BANNED",
    "Board",
    "Device",
    "I2cBus",
    "SpiBus",
    "UartBus",
]
