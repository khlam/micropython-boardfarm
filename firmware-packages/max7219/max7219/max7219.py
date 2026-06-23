"""MAX7219 backend for two 8x32 panels stacked into one 16x32 display.

The backend accepts frames in human-visual coordinates and translates them into
the eight per-chip-row SPI frames required by the cascaded MAX7219 chain.
"""

import utime
from micropython import const

_PANEL_W = const(32)
_PANEL_H = const(8)
_CHIPS_PER_PANEL = const(4)
_PANELS = const(2)
_NUM_CHIPS = const(_CHIPS_PER_PANEL * _PANELS)
_WIDTH = const(_PANEL_W)
_HEIGHT = const(_PANEL_H * _PANELS)
_BYTES_PER_ROW = const(_WIDTH // 8)
_FLASH_MS = const(250)
_DEFAULT_INTENSITY = const(0x00)
_MAX_INTENSITY = const(0x0F)

_MIRROR_X = False
_FLIP_Y = True

_REG_DECODE = const(0x09)
_REG_INTENSITY = const(0x0A)
_REG_SCAN_LIMIT = const(0x0B)
_REG_SHUTDOWN = const(0x0C)
_REG_DISPLAY_TEST = const(0x0F)


class _MAX7219Backend:
    """Hardware backend used by the public ``MAX7219`` facade."""

    def __init__(self, spi: object, cs: object) -> None:
        """Initialise the SPI chain and allocate reusable buffers."""
        self._spi = spi
        self._cs = cs
        self._fb = bytearray(_HEIGHT * _BYTES_PER_ROW)
        self._next_fb = bytearray(_HEIGHT * _BYTES_PER_ROW)
        self._cmd = bytearray(2 * _NUM_CHIPS)
        self._intensity = _DEFAULT_INTENSITY
        self._init_display()

    @property
    def width(self) -> int:
        """Return the backend's fixed visual width."""
        return _WIDTH

    @property
    def height(self) -> int:
        """Return the backend's fixed visual height."""
        return _HEIGHT

    def write_frame(self, frame: object, *, allow_lossy: bool) -> bool:
        """Convert a fitted frame into the binary matrix and refresh.

        Args:
            frame: A ``pixel_display.Frame`` already fitted to the backend size
                and capped to normalized byte intensity values.
            allow_lossy: Whether RGB/grayscale collapse may discard information.

        Returns:
            ``True`` when the frame was represented, ``False`` when the display
            facade should render its failure indicator instead.
        """
        max_intensity = _convert_frame(frame, self._next_fb, allow_lossy=allow_lossy)
        if max_intensity is None:
            return False
        self._fb, self._next_fb = self._next_fb, self._fb
        self._intensity = max_intensity
        self._apply_config()
        self._refresh()
        return True

    def clear(self) -> None:
        """Blank the matrix and flush the cleared framebuffer."""
        _clear_buffer(self._fb)
        self._apply_config()
        self._refresh()

    def _init_display(self) -> None:
        """Run the power-on register sequence, flash all LEDs, and clear."""
        self._write_all(_REG_DISPLAY_TEST, 0x01)
        utime.sleep_ms(_FLASH_MS)
        self._apply_config()
        self.clear()

    def _apply_config(self) -> None:
        """Write steady-state control registers to every chip."""
        for reg, val in (
            (_REG_DISPLAY_TEST, 0x00),
            (_REG_SCAN_LIMIT, 0x07),
            (_REG_DECODE, 0x00),
            (_REG_INTENSITY, self._intensity),
            (_REG_SHUTDOWN, 0x01),
        ):
            self._write_all(reg, val)

    def _write_all(self, register: int, data: int) -> None:
        """Send the same register+data word to every chip in one CS frame."""
        cmd = self._cmd
        for i in range(_NUM_CHIPS):
            cmd[i * 2] = register
            cmd[i * 2 + 1] = data
        self._cs.off()
        self._spi.write(cmd)
        self._cs.on()

    def _refresh(self) -> None:
        """Translate the visual framebuffer to the chain and push it out."""
        fb = self._fb
        cmd = self._cmd
        for chip_row in range(_PANEL_H):
            reg = chip_row + 1
            for chip in range(_NUM_CHIPS):
                panel = chip // _CHIPS_PER_PANEL
                col_chip = chip % _CHIPS_PER_PANEL
                src_row = (_PANEL_H - 1 - chip_row) if _FLIP_Y else chip_row
                vy = panel * _PANEL_H + src_row
                row_base = vy * _BYTES_PER_ROW
                byte = 0
                for bit in range(8):
                    nat_x = col_chip * 8 + bit
                    vx = (_WIDTH - 1 - nat_x) if _MIRROR_X else nat_x
                    if fb[row_base + (vx >> 3)] & (1 << (vx & 7)):
                        byte |= 1 << bit
                pos = _NUM_CHIPS - 1 - chip
                cmd[pos * 2] = reg
                cmd[pos * 2 + 1] = byte
            self._cs.off()
            self._spi.write(cmd)
            self._cs.on()


def _pixel_value(frame: object, x: int, y: int, *, allow_lossy: bool) -> int | None:
    """Return one monochrome normalized byte, or ``None`` on unsupported data."""
    index = (y * frame.width + x) * frame.channels
    if frame.channels == 1:
        return frame.data[index]
    if not allow_lossy:
        return None
    value = 0
    for offset in range(frame.channels):
        channel = frame.data[index + offset]
        value = max(value, channel)
    return value


def _convert_frame(frame: object, buf: bytearray, *, allow_lossy: bool) -> int | None:
    """Convert one frame into a framebuffer and return its MAX7219 intensity."""
    if frame.width != _WIDTH or frame.height != _HEIGHT:
        return None
    _clear_buffer(buf)
    state = [None, 0]
    for y in range(_HEIGHT):
        for x in range(_WIDTH):
            value = _pixel_value(frame, x, y, allow_lossy=allow_lossy)
            if value is None or not _add_pixel(buf, x, y, value, state, allow_lossy=allow_lossy):
                return None
    return _max7219_intensity(state[1])


def _add_pixel(
    buf: bytearray,
    x: int,
    y: int,
    value: int,
    state: list,
    *,
    allow_lossy: bool,
) -> bool:
    """Apply one normalized pixel value to a monochrome framebuffer."""
    if value <= 0:
        return True
    if state[0] is None:
        state[0] = value
    elif value != state[0] and not allow_lossy:
        return False
    state[1] = max(state[1], value)
    _set_pixel(buf, x, y)
    return True


def _max7219_intensity(value: int) -> int:
    """Map a normalized byte intensity to the MAX7219 brightness register."""
    return (value * _MAX_INTENSITY + 127) // 255


def _clear_buffer(buf: bytearray) -> None:
    """Zero a framebuffer buffer in place."""
    for i in range(len(buf)):
        buf[i] = 0


def _set_pixel(buf: bytearray, x: int, y: int) -> None:
    """Set one visual pixel in a framebuffer buffer."""
    idx = y * _BYTES_PER_ROW + (x >> 3)
    buf[idx] |= 1 << (x & 7)
