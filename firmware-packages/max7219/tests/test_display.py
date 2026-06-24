"""Host CPython tests for the MAX7219 pixel-display backend."""

from __future__ import annotations

import machine
import pytest
from fakes import FakeCS, FakeSPI

from max7219 import MAX7219
from max7219.max7219 import (
    _FLIP_Y,
    _MIRROR_X,
    _PANEL_H,
    _REG_DISPLAY_TEST,
    _REG_INTENSITY,
    _REG_SHUTDOWN,
    _WIDTH,
    _MAX7219Backend,
)
from pixel_display import Canvas, Frame, PackedFrame

_NUM_CHIPS = 8


def test_public_facade_exposes_only_show_for_rendering() -> None:
    """Public MAX7219 has no model-specific drawing helpers."""
    assert hasattr(MAX7219, "show")
    assert not hasattr(MAX7219, "show_lines")
    assert not hasattr(MAX7219, "draw_text")
    assert not hasattr(MAX7219, "set_intensity")
    assert not hasattr(MAX7219, "reassert")


def test_public_show_writes_fitted_frame_to_spi() -> None:
    """The public facade routes abstract frames through Display to SPI."""
    display = MAX7219(
        spi_id=1,
        sck=26,
        mosi=27,
        cs=28,
        width_pixels=32,
        height_pixels=16,
        brightness=0.2,
    )
    spi = machine.SPI.instances[-1]
    spi.writes.clear()

    display.show(Frame.text_lines(("GPS", "WAIT")))

    lit = _decode(spi.writes)
    assert lit
    assert any(y < _PANEL_H for _x, y in lit)
    assert any(y >= _PANEL_H for _x, y in lit)
    assert [frame[1] for frame in spi.writes if frame[0] == _REG_INTENSITY][-1] == 3


def test_init_writes_registers_and_toggles_cs() -> None:
    """Backend init flashes, configures, clears, and brackets every SPI frame."""
    _backend, spi, cs = _make_backend()

    assert spi.writes
    assert cs.toggles.count("off") == cs.toggles.count("on") == len(spi.writes)


def test_write_frame_roundtrips_corner_pixels() -> None:
    """A one-channel normalized frame lands on the expected visual pixels."""
    backend, spi, _cs = _make_backend()
    frame = Frame.blank(32, 16)
    corners = {(0, 0), (31, 0), (0, 15), (31, 15), (5, 9)}
    for x, y in corners:
        frame.data[y * frame.width + x] = 15
    spi.writes.clear()

    assert backend.write_frame(frame, allow_lossy=False) is True

    assert _decode(spi.writes) == corners


def test_write_frame_applies_normalized_intensity_without_static_config() -> None:
    """Changing frames write intensity only when needed, not full config."""
    backend, spi, _cs = _make_backend()
    frame = Frame.blank(32, 16)
    frame.data[0] = 128
    spi.writes.clear()

    assert backend.write_frame(frame, allow_lossy=False) is True

    regs = [write[0] for write in spi.writes]
    assert _REG_DISPLAY_TEST not in regs
    assert _REG_SHUTDOWN not in regs
    assert [write[1] for write in spi.writes if write[0] == _REG_INTENSITY][-1] == 8
    assert len(_row_writes(spi.writes)) == 1


def test_packed_frame_dirty_refresh_writes_changed_rows_only() -> None:
    """Packed frames skip fitting and refresh only changed digit rows."""
    backend, spi, _cs = _make_backend()
    canvas = Canvas(32, 16, intensity=128)
    canvas.pixel(0, 0)
    spi.writes.clear()

    assert backend.write_frame(canvas.frame(), allow_lossy=False) is True

    assert [write[1] for write in spi.writes if write[0] == _REG_INTENSITY][-1] == 8
    assert len(_row_writes(spi.writes)) == 1
    assert _decode(spi.writes) == {(0, 0)}

    canvas.pixel(1, 0)
    spi.writes.clear()

    assert backend.write_frame(canvas.frame(), allow_lossy=False) is True
    assert len(_row_writes(spi.writes)) == 1


def test_low_nonzero_intensity_uses_dimmest_register_after_bright_frame() -> None:
    """A very dim lit frame does not inherit the previous brightness register."""
    backend, spi, _cs = _make_backend()
    state = _MatrixState()
    bright = Frame.blank(32, 16)
    bright.data[0] = 255
    assert backend.write_frame(bright, allow_lossy=False) is True
    state.apply(spi.writes)

    dim = Frame.blank(32, 16)
    dim.data[0] = 1
    spi.writes.clear()

    assert backend.write_frame(dim, allow_lossy=False) is True
    state.apply(spi.writes)
    assert [write[1] for write in spi.writes if write[0] == _REG_INTENSITY][-1] == 0
    assert not _row_writes(spi.writes)
    assert (0, 0) in state.lit()


def test_same_packed_bitmap_with_new_intensity_writes_only_intensity() -> None:
    """Brightness-only packed changes avoid row refreshes."""
    backend, spi, _cs = _make_backend()
    canvas = Canvas(32, 16, intensity=255)
    canvas.pixel(0, 0)
    bright = canvas.frame()
    assert backend.write_frame(bright, allow_lossy=False) is True

    dim = PackedFrame(bright.width, bright.height, bright.stride, bright.data, 64)
    spi.writes.clear()

    assert backend.write_frame(dim, allow_lossy=False) is True
    assert not _row_writes(spi.writes)
    assert [write[1] for write in spi.writes if write[0] == _REG_INTENSITY] == [4]


def test_unchanged_show_reasserts_config_and_rows() -> None:
    """An unchanged frame heals chip config and rewrites all digit rows."""
    backend, spi, _cs = _make_backend()
    canvas = Canvas(32, 16, intensity=64)
    canvas.pixel(0, 0)
    frame = canvas.frame()
    assert backend.write_frame(frame, allow_lossy=False) is True
    spi.writes.clear()

    assert backend.write_frame(frame, allow_lossy=False) is True

    regs = [write[0] for write in spi.writes]
    assert _REG_DISPLAY_TEST in regs
    assert _REG_SHUTDOWN in regs
    assert [write[1] for write in spi.writes if write[0] == _REG_INTENSITY] == [4]
    assert len(_row_writes(spi.writes)) == _PANEL_H


def test_varying_grayscale_requires_lossy_override() -> None:
    """MAX7219 can show one global brightness, not per-pixel grayscale."""
    backend, spi, _cs = _make_backend()
    frame = Frame.blank(32, 16)
    frame.data[0] = 64
    frame.data[1] = 128
    spi.writes.clear()

    assert backend.write_frame(frame, allow_lossy=False) is False
    assert not spi.writes

    assert backend.write_frame(frame, allow_lossy=True) is True
    assert {write[1] for write in spi.writes if write[0] == _REG_INTENSITY} == {8}


def test_rgb_requires_lossy_override_for_monochrome_conversion() -> None:
    """RGB frames are converted to monochrome only when lossy conversion is allowed."""
    backend, spi, _cs = _make_backend()
    frame = Frame.blank(32, 16, channels=3)
    frame.data[0:3] = bytearray((0, 5, 0))
    spi.writes.clear()

    assert backend.write_frame(frame, allow_lossy=False) is False
    assert not spi.writes

    assert backend.write_frame(frame, allow_lossy=True) is True
    assert (0, 0) in _decode(spi.writes)


def test_wrong_geometry_is_not_represented() -> None:
    """The backend refuses frames not fitted to its hardware geometry."""
    backend, spi, _cs = _make_backend()
    spi.writes.clear()

    assert backend.write_frame(Frame.blank(16, 16), allow_lossy=True) is False
    assert not spi.writes


def test_clear_blanks_framebuffer_and_refreshes() -> None:
    """Clear sends an all-off frame after applying recovery config."""
    backend, spi, _cs = _make_backend()
    state = _MatrixState()
    frame = Frame.blank(32, 16)
    frame.data[0] = 15
    backend.write_frame(frame, allow_lossy=False)
    state.apply(spi.writes)
    spi.writes.clear()

    backend.clear()

    state.apply(spi.writes)
    regs = [write[0] for write in spi.writes]
    assert _REG_DISPLAY_TEST in regs
    assert _REG_SHUTDOWN in regs
    assert len(_row_writes(spi.writes)) == _PANEL_H
    assert not state.lit()


def _make_backend() -> tuple[_MAX7219Backend, FakeSPI, FakeCS]:
    """Build a backend with local fakes."""
    spi, cs = FakeSPI(), FakeCS()
    return _MAX7219Backend(spi, cs), spi, cs


def _row_writes(writes: list[bytes]) -> list[bytes]:
    """Return only digit-register row writes."""
    return [write for write in writes if 1 <= write[0] <= _PANEL_H]


class _MatrixState:
    """Incremental MAX7219 matrix state reconstructed from SPI writes."""

    def __init__(self) -> None:
        """Start with no known lit row data."""
        self._rows: list[bytes] = []

    def apply(self, writes: list[bytes]) -> None:
        """Apply row writes to the simulated chip state."""
        for write in writes:
            if not 1 <= write[0] <= _PANEL_H:
                continue
            reg = write[0]
            while len(self._rows) < reg:
                self._rows.append(bytes(2 * _NUM_CHIPS))
            self._rows[reg - 1] = write

    def lit(self) -> set[tuple[int, int]]:
        """Return visible lit pixels from the accumulated row state."""
        return _decode(self._rows)


def _decode(writes: list[bytes]) -> set[tuple[int, int]]:
    """Reconstruct lit visual pixels from MAX7219 SPI frames."""
    lit: set[tuple[int, int]] = set()
    for frame in writes:
        reg = frame[0]
        if not 1 <= reg <= _PANEL_H:
            continue
        chip_row = reg - 1
        for pos in range(_NUM_CHIPS):
            data = frame[pos * 2 + 1]
            chip = _NUM_CHIPS - 1 - pos
            panel, col_chip = divmod(chip, 4)
            src_row = (_PANEL_H - 1 - chip_row) if _FLIP_Y else chip_row
            vy = panel * _PANEL_H + src_row
            for bit in range(8):
                if data & (1 << bit):
                    nat_x = col_chip * 8 + bit
                    vx = (_WIDTH - 1 - nat_x) if _MIRROR_X else nat_x
                    lit.add((vx, vy))
    return lit


@pytest.fixture(autouse=True)
def _reset_machine() -> None:
    """Clear machine stub state around each case."""
    machine.reset()
