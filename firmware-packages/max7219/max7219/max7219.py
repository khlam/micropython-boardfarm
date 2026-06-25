"""MAX7219 backend for two 8x32 panels stacked into one 16x32 display.

The backend accepts frames in human-visual coordinates and translates them into
the eight per-chip-row SPI frames required by the cascaded MAX7219 chain.
"""

import utime
from micropython import const

from pixel_frame import Frame

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
        self._rows = bytearray(_PANEL_H * _NUM_CHIPS)
        self._next_rows = bytearray(_PANEL_H * _NUM_CHIPS)
        self._cmd = bytearray(2 * _NUM_CHIPS)
        self._intensity = _DEFAULT_INTENSITY
        self._rotated = False
        self._last_frame = None
        self._last_allow_lossy = False
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
            frame: A fitted ``pixel_frame.Frame`` or ``MatrixFrame`` capped to
                normalized byte intensity values.
            allow_lossy: Whether RGB/grayscale collapse may discard information.

        Returns:
            ``True`` when the frame was represented, ``False`` when the display
            facade should render its failure indicator instead.
        """
        max_intensity = _convert_frame(
            frame,
            self._next_rows,
            allow_lossy=allow_lossy,
            rotate=self._rotated,
        )
        if max_intensity is None:
            return False
        self._last_frame = frame
        self._last_allow_lossy = allow_lossy
        rows_changed = _buffers_differ(self._rows, self._next_rows)
        intensity_changed = max_intensity != self._intensity
        if intensity_changed:
            self._intensity = max_intensity
            self._write_intensity()
        if rows_changed:
            self._refresh_dirty()
            _copy_buffer(self._next_rows, self._rows)
        elif not intensity_changed:
            self._reassert()
        return True

    def flip(self) -> None:
        """Rotate the whole 16x32 surface 180 degrees and re-render now.

        The rotation is applied in visual space across the full display
        (``(x, y) -> (W-1-x, H-1-y)``), so the two stacked 8x32 panels swap
        places rather than each flipping internally. The last shown frame is
        re-converted under the new orientation and pushed immediately, rather
        than waiting for the next caller refresh.
        """
        self._rotated = not self._rotated
        if self._last_frame is not None:
            self.write_frame(self._last_frame, allow_lossy=self._last_allow_lossy)

    def clear(self) -> None:
        """Blank the matrix and flush the cleared framebuffer."""
        _clear_buffer(self._next_rows)
        self._write_static_config()
        self._write_intensity()
        self._write_all_rows(self._next_rows)
        _copy_buffer(self._next_rows, self._rows)

    def _init_display(self) -> None:
        """Run the power-on register sequence, flash all LEDs, and clear."""
        self._write_all(_REG_DISPLAY_TEST, 0x01)
        utime.sleep_ms(_FLASH_MS)
        self.clear()

    def _write_static_config(self) -> None:
        """Write steady-state control registers that rarely change."""
        for reg, val in (
            (_REG_DISPLAY_TEST, 0x00),
            (_REG_SCAN_LIMIT, 0x07),
            (_REG_DECODE, 0x00),
            (_REG_SHUTDOWN, 0x01),
        ):
            self._write_all(reg, val)

    def _write_intensity(self) -> None:
        """Write the current global intensity register to every chip."""
        self._write_all(_REG_INTENSITY, self._intensity)

    def _write_all(self, register: int, data: int) -> None:
        """Send the same register+data word to every chip in one CS frame."""
        cmd = self._cmd
        for i in range(_NUM_CHIPS):
            cmd[i * 2] = register
            cmd[i * 2 + 1] = data
        self._cs.off()
        self._spi.write(cmd)
        self._cs.on()

    def _write_row(self, chip_row: int, rows: bytearray) -> None:
        """Write one digit register row across the whole chip chain."""
        base = chip_row * _NUM_CHIPS
        cmd = self._cmd
        reg = chip_row + 1
        for pos in range(_NUM_CHIPS):
            cmd[pos * 2] = reg
            cmd[pos * 2 + 1] = rows[base + pos]
        self._cs.off()
        self._spi.write(cmd)
        self._cs.on()

    def _write_all_rows(self, rows: bytearray) -> None:
        """Write all digit register rows."""
        for chip_row in range(_PANEL_H):
            self._write_row(chip_row, rows)

    def _refresh_dirty(self) -> None:
        """Write only digit rows whose chain bytes changed."""
        for chip_row in range(_PANEL_H):
            base = chip_row * _NUM_CHIPS
            dirty = False
            for pos in range(_NUM_CHIPS):
                if self._rows[base + pos] != self._next_rows[base + pos]:
                    dirty = True
                    break
            if dirty:
                self._write_row(chip_row, self._next_rows)

    def _reassert(self) -> None:
        """Heal the chip configuration and current matrix state."""
        self._write_static_config()
        self._write_intensity()
        self._write_all_rows(self._rows)


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


def _convert_frame(
    frame: object,
    buf: bytearray,
    *,
    allow_lossy: bool,
    rotate: bool,
) -> int | None:
    """Convert one frame into chain rows and return its MAX7219 intensity."""
    if isinstance(frame, Frame):
        return _convert_packed_frame(frame, buf, rotate=rotate)
    return _convert_byte_frame(frame, buf, allow_lossy=allow_lossy, rotate=rotate)


def _convert_packed_frame(frame: Frame, buf: bytearray, *, rotate: bool) -> int | None:
    """Convert one packed frame directly into MAX7219 chain rows."""
    if frame.width != _WIDTH or frame.height != _HEIGHT:
        return None
    if frame.intensity <= 0:
        _clear_buffer(buf)
        return _DEFAULT_INTENSITY
    for chip_row in range(_PANEL_H):
        base = chip_row * _NUM_CHIPS
        for chip in range(_NUM_CHIPS):
            panel = chip // _CHIPS_PER_PANEL
            col_chip = chip % _CHIPS_PER_PANEL
            src_row = (_PANEL_H - 1 - chip_row) if _FLIP_Y else chip_row
            vy = panel * _PANEL_H + src_row
            pos = _NUM_CHIPS - 1 - chip
            buf[base + pos] = _packed_chip_byte(frame, col_chip, vy, rotate=rotate)
    return _max7219_intensity(frame.intensity)


def _convert_byte_frame(
    frame: object,
    buf: bytearray,
    *,
    allow_lossy: bool,
    rotate: bool,
) -> int | None:
    """Convert one byte-per-pixel frame into MAX7219 chain rows."""
    if frame.width != _WIDTH or frame.height != _HEIGHT:
        return None
    _clear_buffer(buf)
    state = [None, 0]
    for y in range(_HEIGHT):
        for x in range(_WIDTH):
            value = _pixel_value(frame, x, y, allow_lossy=allow_lossy)
            if value is None or not _add_pixel(
                buf, x, y, value, state, allow_lossy=allow_lossy, rotate=rotate
            ):
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
    rotate: bool,
) -> bool:
    """Apply one normalized pixel value to a monochrome framebuffer."""
    if value <= 0:
        return True
    if state[0] is None:
        state[0] = value
    elif value != state[0] and not allow_lossy:
        return False
    state[1] = max(state[1], value)
    if rotate:
        x = _WIDTH - 1 - x
        y = _HEIGHT - 1 - y
    _set_visual_pixel(buf, x, y)
    return True


def _max7219_intensity(value: int) -> int:
    """Map a normalized byte intensity to the MAX7219 brightness register."""
    return (value * _MAX_INTENSITY + 127) // 255


def _clear_buffer(buf: bytearray) -> None:
    """Zero a framebuffer buffer in place."""
    for i in range(len(buf)):
        buf[i] = 0


def _copy_buffer(src: bytearray, dst: bytearray) -> None:
    """Copy one same-sized buffer into another."""
    for i, value in enumerate(src):
        dst[i] = value


def _buffers_differ(left: bytearray, right: bytearray) -> bool:
    """Return whether two same-sized buffers contain different bytes."""
    return any(value != right[i] for i, value in enumerate(left))


def _packed_chip_byte(frame: Frame, col_chip: int, vy: int, *, rotate: bool) -> int:
    """Return one chip byte for hardware visual row ``vy`` and column block.

    Folds the fixed ``_MIRROR_X`` hardware mapping and the optional 180-degree
    visual rotation into the source read. When neither applies the packed byte
    can be copied straight through, which keeps the common path cheap.
    """
    if not _MIRROR_X and not rotate:
        return frame.data[(vy * frame.stride) + col_chip]
    byte = 0
    src_y = (_HEIGHT - 1 - vy) if rotate else vy
    for bit in range(8):
        nat_x = col_chip * 8 + bit
        vx = (_WIDTH - 1 - nat_x) if _MIRROR_X else nat_x
        src_x = (_WIDTH - 1 - vx) if rotate else vx
        if frame.data[(src_y * frame.stride) + (src_x >> 3)] & (1 << (src_x & 7)):
            byte |= 1 << bit
    return byte


def _set_visual_pixel(buf: bytearray, x: int, y: int) -> None:
    """Set one visual pixel in a chain-row buffer."""
    panel = y // _PANEL_H
    src_row = y % _PANEL_H
    chip_row = (_PANEL_H - 1 - src_row) if _FLIP_Y else src_row
    nat_x = (_WIDTH - 1 - x) if _MIRROR_X else x
    col_chip = nat_x >> 3
    chip = (panel * _CHIPS_PER_PANEL) + col_chip
    pos = _NUM_CHIPS - 1 - chip
    idx = (chip_row * _NUM_CHIPS) + pos
    buf[idx] |= 1 << (nat_x & 7)
