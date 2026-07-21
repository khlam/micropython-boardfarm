"""MicroPython framebuffer driver for SSD1306 OLED displays over I²C.

The controller setup and framebuffer protocol follow MicroPython's SSD1306
driver. This repository-facing class adds flat-pin bus construction and an
address scan so project firmware can distinguish missing hardware from an I²C
initialisation failure.
"""

import framebuf
from micropython import const

from i2c_bus import DeviceNotFoundError, soft_i2c

_SET_CONTRAST = const(0x81)
_SET_ENTIRE_ON = const(0xA4)
_SET_NORM_INV = const(0xA6)
_SET_DISP = const(0xAE)
_SET_MEM_ADDR = const(0x20)
_SET_COL_ADDR = const(0x21)
_SET_PAGE_ADDR = const(0x22)
_SET_DISP_START_LINE = const(0x40)
_SET_SEG_REMAP = const(0xA0)
_SET_MUX_RATIO = const(0xA8)
_SET_COM_OUT_DIR = const(0xC0)
_SET_DISP_OFFSET = const(0xD3)
_SET_COM_PIN_CFG = const(0xDA)
_SET_DISP_CLK_DIV = const(0xD5)
_SET_PRECHARGE = const(0xD9)
_SET_VCOM_DESEL = const(0xDB)
_SET_CHARGE_PUMP = const(0x8D)

_COMMAND_PREFIX = const(0x80)
_DATA_PREFIX = b"\x40"


class SSD1306(framebuf.FrameBuffer):
    """SSD1306 framebuffer backed by a self-managed software-I²C bus.

    Attributes:
        i2c: The software-I²C bus opened by the driver.
        address: Configured 7-bit display address.
        width: Framebuffer width in pixels.
        height: Framebuffer height in pixels.
        buffer: Monochrome vertical-LSB framebuffer storage.
    """

    def __init__(
        self,
        *,
        sda: int,
        scl: int,
        width: int = 128,
        height: int = 64,
        address: int = 0x3C,
        external_vcc: bool = False,
        freq: int = 400_000,
    ) -> None:
        """Open the bus, verify the display, and initialise its framebuffer.

        Args:
            sda: GPIO number for the I²C data line.
            scl: GPIO number for the I²C clock line.
            width: Display width in pixels.
            height: Display height in pixels; must be divisible by eight.
            address: 7-bit I²C address, normally 0x3C.
            external_vcc: Whether the panel uses an external OLED voltage
                instead of the controller's charge pump.
            freq: I²C bus clock in Hz. Defaults to 400 kHz: unlike the ToF
                sensors that force ``soft_i2c`` down to 100 kHz for clock
                stretching, the SSD1306 does not clock-stretch, and ``show``
                flushes the whole framebuffer, so the faster bus keeps that
                full-frame write ~4x shorter.

        Raises:
            ValueError: The requested dimensions cannot form SSD1306 pages.
            DeviceNotFoundError: No device ACKed at ``address``.
        """
        if width <= 0 or height <= 0 or height % 8:
            raise ValueError("SSD1306 dimensions must be positive and height divisible by 8")

        i2c = soft_i2c(sda, scl, freq)
        if address not in i2c.scan():
            raise DeviceNotFoundError(f"SSD1306 not found at 0x{address:02x}")

        self.i2c = i2c
        self.address = address
        self.width = width
        self.height = height
        self.external_vcc = external_vcc
        self.pages = height // 8
        self.buffer = bytearray(self.pages * width)
        self._command = bytearray(2)
        super().__init__(self.buffer, width, height, framebuf.MONO_VLSB)
        self._init_display()

    def poweroff(self) -> None:
        """Put the controller into display-off mode without clearing RAM."""
        self._write_command(_SET_DISP)

    def poweron(self) -> None:
        """Put the controller into display-on mode."""
        self._write_command(_SET_DISP | 0x01)

    def contrast(self, value: int) -> None:
        """Set display contrast to an unsigned byte value.

        Args:
            value: Contrast level from 0 through 255.
        """
        self._write_command(_SET_CONTRAST)
        self._write_command(value & 0xFF)

    def invert(self, invert: bool) -> None:  # noqa: FBT001
        """Select normal or inverted pixels.

        Args:
            invert: True for inverted pixels, False for normal pixels.
        """
        self._write_command(_SET_NORM_INV | int(bool(invert)))

    def show(self) -> None:
        """Flush the framebuffer to the display's graphics RAM."""
        column_offset = 32 if self.width == 64 else 0
        self._write_command(_SET_COL_ADDR)
        self._write_command(column_offset)
        self._write_command(column_offset + self.width - 1)
        self._write_command(_SET_PAGE_ADDR)
        self._write_command(0)
        self._write_command(self.pages - 1)
        self.i2c.writevto(self.address, (_DATA_PREFIX, self.buffer))

    def _init_display(self) -> None:
        """Send the controller setup sequence and blank the panel."""
        for command in (
            _SET_DISP,
            _SET_MEM_ADDR,
            0x00,
            _SET_DISP_START_LINE,
            _SET_SEG_REMAP | 0x01,
            _SET_MUX_RATIO,
            self.height - 1,
            _SET_COM_OUT_DIR | 0x08,
            _SET_DISP_OFFSET,
            0x00,
            _SET_COM_PIN_CFG,
            0x02 if self.width > 2 * self.height else 0x12,
            _SET_DISP_CLK_DIV,
            0x80,
            _SET_PRECHARGE,
            0x22 if self.external_vcc else 0xF1,
            _SET_VCOM_DESEL,
            0x30,
            _SET_CONTRAST,
            0xFF,
            _SET_ENTIRE_ON,
            _SET_NORM_INV,
            _SET_CHARGE_PUMP,
            0x10 if self.external_vcc else 0x14,
            _SET_DISP | 0x01,
        ):
            self._write_command(command)
        self.fill(0)
        self.show()

    def _write_command(self, command: int) -> None:
        """Write one command byte using the SSD1306 I²C control prefix.

        Args:
            command: Unsigned controller command byte.
        """
        self._command[0] = _COMMAND_PREFIX
        self._command[1] = command
        self.i2c.writeto(self.address, self._command)
