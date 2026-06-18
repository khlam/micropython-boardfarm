"""RP2350 board pin topology.

Mirrors the RP2040-Zero edge wiring: UART1 GP4 / GP5, SPI1 GP10 / GP11 + CS GP9,
I2C0 GP0 / GP1. The status LED is the CYW43-routed ``"LED"`` (digital on/off),
owned by ``boot_status_led`` and documented here only — hence a string, not a
GPIO number.
"""

from board_pinout import Board, Device, I2cBus, SpiBus, UartBus

BOARD = Board(
    name="RP2350",
    status_led="LED",
    spi=SpiBus(id=1, sck=10, mosi=11, miso=None),  # write-only display: no MISO
    i2c=I2cBus(id=0, sda=0, scl=1),
    uart=UartBus(id=1, tx=4, rx=5),
    devices={
        "gps": Device(bus="uart", cs=None, addr=None),
        "display": Device(bus="spi", cs=9, addr=None),
    },
)
