"""RP2040-Zero (Waveshare) board pin topology.

All signal pins are on the castellated edge headers. The MAX7219 SPI moved to
SPI1 (GP10 / GP11 + CS GP9) and the GPS UART to UART1 (GP4 / GP5) so nothing
lands on the underside solder pads GP17/GP18/GP19 (see
``board_pinout.RP2040_ZERO_BANNED``). The on-board WS2812 (GP16) is owned by
``boot_status_led``; it is documented here for completeness only.
"""

from board_pinout import Board, Device, I2cBus, SpiBus, UartBus

BOARD = Board(
    name="RP2040-Zero",
    status_led=16,
    spi=SpiBus(id=1, sck=10, mosi=11, miso=None),  # write-only display: no MISO
    i2c=I2cBus(id=0, sda=0, scl=1),
    uart=UartBus(id=1, tx=4, rx=5),
    devices={
        "gps": Device(bus="uart", cs=None, addr=None),
        "display": Device(bus="spi", cs=9, addr=None),
    },
)
