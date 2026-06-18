"""ESP32-S3-Zero (Waveshare) board pin topology.

The ESP32 GPIO matrix routes most functions to any pin, so these keep the
established wiring: UART1 GPIO17 / GPIO18, SPI1 GPIO12 / GPIO11 + CS GPIO10, I2C0
GPIO1 / GPIO2. The on-board WS2812 (GPIO21) is owned by ``boot_status_led`` and
documented here only.
"""

from board_pinout import Board, Device, I2cBus, SpiBus, UartBus

BOARD = Board(
    name="ESP32-S3-Zero",
    status_led=21,
    spi=SpiBus(id=1, sck=12, mosi=11, miso=None),  # write-only display: no MISO
    i2c=I2cBus(id=0, sda=1, scl=2),
    uart=UartBus(id=1, tx=17, rx=18),
    devices={
        "gps": Device(bus="uart", cs=None, addr=None),
        "display": Device(bus="spi", cs=10, addr=None),
    },
)
