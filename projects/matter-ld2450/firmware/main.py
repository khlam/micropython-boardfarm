"""Declare the hardware configuration for the Matter LD2450 scaffold.

The board mapping reserves the radar UART without opening it. Radar lifecycle,
Matter endpoint selection, and the mapping between target reports and product
state remain undefined until the product contract is established.
"""

import os
from collections import namedtuple

# This table is the wiring for this project. ``uart_id`` selects the peripheral,
# ``tx`` connects to radar RX, and ``rx`` connects to radar TX.
Board = namedtuple("Board", ("name", "uart_id", "tx", "rx"))
_machine = os.uname().machine
if "ESP32S3" not in _machine:
    raise RuntimeError(f"unsupported board: {_machine}")
BOARD = Board(name="ESP32-S3-Zero", uart_id=1, tx=5, rx=6)
