"""MCU-micropython register-level driver for the SSD1306 monochrome OLED over I²C.

Chip-agnostic with respect to the MCU: takes a ``machine.I2C`` (or
``SoftI2C``) instance from the caller and never imports ``machine`` itself.
The display dimensions are constructor parameters, so the same driver covers
128x64 and 128x32 panels (the COM-pin and multiplex configuration is derived
from ``height``).

The driver owns a single MONO_VLSB framebuffer (one byte spans eight vertical
pixels of one column within an 8-row page) and never subclasses ``framebuf``,
so it has no native-module dependency and is exercisable on the host. Every
transfer is framed as ``writeto_mem(addr, control, payload)`` where the SSD1306
control byte is ``0x00`` for a command stream and ``0x40`` for GDDRAM data —
which is exactly the byte the I²C peripheral emits right after the address.
"""

from micropython import const

_SET_DISP = const(0xAE)  # 0xAE off, |0x01 on
_SET_MEM_ADDR = const(0x20)
_SET_DISP_START_LINE = const(0x40)
_SET_SEG_REMAP = const(0xA1)  # column 127 -> SEG0
_SET_MUX_RATIO = const(0xA8)
_SET_COM_OUT_DIR = const(0xC8)  # scan from COM[N-1] to COM0
_SET_DISP_OFFSET = const(0xD3)
_SET_COM_PIN_CFG = const(0xDA)
_SET_DISP_CLK_DIV = const(0xD5)
_SET_PRECHARGE = const(0xD9)
_SET_VCOM_DESEL = const(0xDB)
_SET_CONTRAST = const(0x81)
_SET_ENTIRE_ON = const(0xA4)  # follow RAM contents
_SET_NORM_INV = const(0xA6)  # non-inverted
_SET_CHARGE_PUMP = const(0x8D)
_SET_COL_ADDR = const(0x21)
_SET_PAGE_ADDR = const(0x22)

_CTRL_CMD = const(0x00)
_CTRL_DATA = const(0x40)

_PAGE_HEIGHT = const(8)

# SSD1306 modules answer at 0x3C by default; a few strap 0x3D.
OLED_ADDRS = (0x3C, 0x3D)


class ScreenSize:
    """Supported SSD1306 panel dimensions.  Pass one value as ``(width, height)`` to ``SSD1306``."""

    RES_128x32 = (128, 32)
    RES_128x64 = (128, 64)

    @staticmethod
    def frame_ms(size: tuple) -> int:
        """Return the fastest sustainable frame interval in ms for ``size``.

        Args:
            size: One of ``RES_128x32`` or ``RES_128x64``.

        Returns:
            Frame interval in milliseconds (16 for the half-height panel, 33 for full).
        """
        _, height = size
        return 16 if height == 32 else 33


class SSD1306:
    """SSD1306 OLED driver exposing a raw framebuffer (``pixel`` / ``fill`` / ``show``)."""

    def __init__(self, i2c: object, width: int, height: int, addr: int = 0x3C) -> None:
        """Configure the panel and allocate its framebuffer.

        Args:
            i2c: A ``machine.I2C``/``SoftI2C`` exposing ``writeto_mem``.
            width: Panel width in pixels (columns).
            height: Panel height in pixels; must be a multiple of 8.
            addr: 7-bit I²C address (0x3C default, 0x3D on some modules).
        """
        self.i2c = i2c
        self.addr = addr
        self.width = width
        self.height = height
        self.pages = height // _PAGE_HEIGHT
        # Pre-allocated MONO_VLSB framebuffer reused every frame — fill()/show()
        # mutate it in place so the render loop allocates nothing per frame.
        self._buf = bytearray(width * self.pages)
        self._init_display()

    def _cmd(self, *values: int) -> None:
        """Send one command stream (one or more command bytes) to the panel."""
        self.i2c.writeto_mem(self.addr, _CTRL_CMD, bytes(values))

    def _init_display(self) -> None:
        """Run the power-on init sequence for an internally-regulated panel.

        COM-pin config depends on the panel geometry: tall 64-row panels use
        alternating COM pins (0x12); short 32-row panels use sequential (0x02).
        """
        com_pins = 0x02 if self.height == 32 else 0x12
        self._cmd(_SET_DISP)  # display off while reconfiguring
        self._cmd(_SET_MEM_ADDR, 0x00)  # horizontal addressing mode
        self._cmd(_SET_DISP_START_LINE)
        self._cmd(_SET_SEG_REMAP)
        self._cmd(_SET_MUX_RATIO, self.height - 1)
        self._cmd(_SET_COM_OUT_DIR)
        self._cmd(_SET_DISP_OFFSET, 0x00)
        self._cmd(_SET_COM_PIN_CFG, com_pins)
        self._cmd(_SET_DISP_CLK_DIV, 0x80)
        self._cmd(_SET_PRECHARGE, 0xF1)  # internal Vcc
        self._cmd(_SET_VCOM_DESEL, 0x30)
        self._cmd(_SET_CONTRAST, 0xFF)
        self._cmd(_SET_ENTIRE_ON)
        self._cmd(_SET_NORM_INV)
        self._cmd(_SET_CHARGE_PUMP, 0x14)  # enable internal charge pump
        self._cmd(_SET_DISP | 0x01)  # display on
        self.fill(0)
        self.show()

    def fill(self, color: int) -> None:
        """Set every pixel in the framebuffer to ``color`` (0 = off, non-zero = on).

        Mutates the pre-allocated buffer in place rather than rebinding it, so
        no temporary allocation happens on the per-frame clear path.
        """
        value = 0xFF if color else 0x00
        for i in range(len(self._buf)):
            self._buf[i] = value

    def pixel(self, x: int, y: int, color: int) -> None:
        """Set the pixel at (x, y); out-of-bounds coordinates are a silent no-op.

        Args:
            x: Column, 0 ≤ x < width.
            y: Row, 0 ≤ y < height.
            color: 0 clears the pixel, any other value sets it.
        """
        if not (0 <= x < self.width and 0 <= y < self.height):
            return
        index = x + (y >> 3) * self.width
        bit = 1 << (y & 0x07)
        if color:
            self._buf[index] |= bit
        else:
            self._buf[index] &= ~bit & 0xFF

    def show(self) -> None:
        """Flush the framebuffer to GDDRAM over I²C in a single data transfer."""
        self._cmd(_SET_COL_ADDR, 0, self.width - 1)
        self._cmd(_SET_PAGE_ADDR, 0, self.pages - 1)
        self.i2c.writeto_mem(self.addr, _CTRL_DATA, self._buf)
