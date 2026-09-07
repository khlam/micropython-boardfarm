"""Host CPython tests for the MAX7219 pixel-display backend.

Covers the chain wiring (which SPI frame lights which visual pixel), the
dirty-row and intensity write policy, monochrome conversion limits, and the
180-degree flip. The decoder below deliberately restates the panel layout from
the hardware wiring rather than importing the driver's ``_FLIP_Y``/``_MIRROR_X``
constants, so an orientation regression fails here instead of flipping encoder
and decoder in lockstep.
"""

from __future__ import annotations

import machine
import pytest
from fake_max7219 import FakeCS, FakeSPI

from max7219 import MAX7219
from max7219.max7219 import (
    _PANEL_H,
    _REG_DISPLAY_TEST,
    _REG_INTENSITY,
    _REG_SHUTDOWN,
    _MAX7219Backend,
)
from pixel_frame import Frame, MatrixFrame

_NUM_CHIPS = 8
_WIDTH = 32
_HEIGHT = 16


def test_facade_reports_declared_geometry() -> None:
    display = _make_facade()

    assert (display.width_pixels, display.height_pixels) == (32, 16)


def test_facade_opens_spi_with_the_documented_bus_settings() -> None:
    _make_facade()
    spi = machine.SPI.instances[-1]

    assert spi.baudrate == 1_000_000
    assert (spi.polarity, spi.phase) == (0, 0)


def test_facade_show_routes_frames_through_display_to_spi() -> None:
    display = _make_facade(brightness=0.2)
    spi = machine.SPI.instances[-1]
    spi.writes.clear()

    frame = Frame(32, 16, intensity=255)
    frame.pixel(1, 2)  # top panel
    frame.pixel(9, 11)  # bottom panel
    display.show(frame)

    assert _decode(spi.writes) == {(1, 2), (9, 11)}
    # brightness 0.2 caps the byte intensity at 51, which maps to register 3.
    assert _intensity_writes(spi.writes)[-1] == 3


def test_facade_flip_reaches_the_backend() -> None:
    display = _make_facade()
    spi = machine.SPI.instances[-1]
    frame = Frame(32, 16, intensity=255)
    frame.pixel(0, 0)
    display.show(frame)
    spi.writes.clear()

    display.flip()

    assert _decode(spi.writes) == {(31, 15)}


def test_top_left_pixel_lands_on_the_documented_chain_bytes() -> None:
    backend, spi, _cs = _make_backend()
    frame = Frame(32, 16, intensity=255)
    frame.pixel(0, 0)
    spi.writes.clear()

    assert backend.write_frame(frame, allow_lossy=False) is True

    # Visual (0,0) is the top panel's first row. FLIP_Y maps it to digit
    # register 8, and the chain is written last-chip-first, so the lit byte is
    # the final chip's payload.
    row = _row_writes(spi.writes)[0]
    assert row == b"\x08\x00" * 7 + b"\x08\x01"


def test_bottom_panel_pixel_lands_on_the_second_chip_group() -> None:
    backend, spi, _cs = _make_backend()
    frame = Frame(32, 16, intensity=255)
    frame.pixel(0, 8)
    spi.writes.clear()

    assert backend.write_frame(frame, allow_lossy=False) is True

    # Same digit register, but the bottom panel occupies chips 4-7, which sit
    # at chain position 3 rather than 7.
    row = _row_writes(spi.writes)[0]
    assert row == b"\x08\x00" * 3 + b"\x08\x01" + b"\x08\x00" * 4


def test_init_writes_registers_and_brackets_every_frame_with_cs() -> None:
    _backend, spi, cs = _make_backend()

    assert spi.writes
    assert cs.toggles.count("off") == cs.toggles.count("on") == len(spi.writes)


def test_write_frame_roundtrips_pixels_across_both_panels() -> None:
    backend, spi, _cs = _make_backend()
    frame = MatrixFrame.blank(32, 16)
    corners = {(0, 0), (31, 0), (0, 15), (31, 15), (5, 9)}
    for x, y in corners:
        frame.data[y * frame.width + x] = 15
    spi.writes.clear()

    assert backend.write_frame(frame, allow_lossy=False) is True

    assert _decode(spi.writes) == corners


def test_changed_frames_write_intensity_without_full_static_config() -> None:
    backend, spi, _cs = _make_backend()
    frame = MatrixFrame.blank(32, 16)
    frame.data[0] = 128
    spi.writes.clear()

    assert backend.write_frame(frame, allow_lossy=False) is True

    regs = [write[0] for write in spi.writes]
    assert _REG_DISPLAY_TEST not in regs
    assert _REG_SHUTDOWN not in regs
    assert _intensity_writes(spi.writes)[-1] == 8
    assert len(_row_writes(spi.writes)) == 1


def test_packed_frames_refresh_only_changed_digit_rows() -> None:
    backend, spi, _cs = _make_backend()
    frame = Frame(32, 16, intensity=128)
    frame.pixel(0, 0)
    spi.writes.clear()

    assert backend.write_frame(frame, allow_lossy=False) is True

    assert _intensity_writes(spi.writes)[-1] == 8
    assert len(_row_writes(spi.writes)) == 1
    assert _decode(spi.writes) == {(0, 0)}

    frame.pixel(1, 0)  # same digit row, so still exactly one row write
    spi.writes.clear()

    assert backend.write_frame(frame, allow_lossy=False) is True
    assert len(_row_writes(spi.writes)) == 1


def test_a_dim_frame_does_not_inherit_the_previous_brightness() -> None:
    backend, spi, _cs = _make_backend()
    state = _MatrixState()
    bright = MatrixFrame.blank(32, 16)
    bright.data[0] = 255
    assert backend.write_frame(bright, allow_lossy=False) is True
    state.apply(spi.writes)

    dim = MatrixFrame.blank(32, 16)
    dim.data[0] = 1
    spi.writes.clear()

    assert backend.write_frame(dim, allow_lossy=False) is True

    state.apply(spi.writes)
    assert _intensity_writes(spi.writes)[-1] == 0
    assert not _row_writes(spi.writes)  # same bitmap, only brightness moved
    assert state.lit() == {(0, 0)}


def test_same_bitmap_with_new_intensity_writes_only_intensity() -> None:
    backend, spi, _cs = _make_backend()
    bright = Frame(32, 16, intensity=255)
    bright.pixel(0, 0)
    assert backend.write_frame(bright, allow_lossy=False) is True

    dim = Frame.from_packed(bright.width, bright.height, bright.stride, bright.data, 64)
    spi.writes.clear()

    assert backend.write_frame(dim, allow_lossy=False) is True

    assert not _row_writes(spi.writes)
    assert _intensity_writes(spi.writes) == [4]


def test_zero_intensity_packed_frame_blanks_the_matrix() -> None:
    backend, spi, _cs = _make_backend()
    lit = Frame(32, 16, intensity=255)
    lit.pixel(4, 4)
    assert backend.write_frame(lit, allow_lossy=False) is True
    state = _MatrixState()
    state.apply(spi.writes)
    spi.writes.clear()

    dark = Frame(32, 16, intensity=0)
    dark.pixel(4, 4)
    assert backend.write_frame(dark, allow_lossy=False) is True

    state.apply(spi.writes)
    assert not state.lit()


def test_unchanged_frame_reasserts_config_and_all_rows() -> None:
    backend, spi, _cs = _make_backend()
    frame = Frame(32, 16, intensity=64)
    frame.pixel(0, 0)
    assert backend.write_frame(frame, allow_lossy=False) is True
    spi.writes.clear()

    assert backend.write_frame(frame, allow_lossy=False) is True

    regs = [write[0] for write in spi.writes]
    assert _REG_DISPLAY_TEST in regs
    assert _REG_SHUTDOWN in regs
    assert _intensity_writes(spi.writes) == [4]
    assert len(_row_writes(spi.writes)) == _PANEL_H


def test_varying_grayscale_requires_the_lossy_override() -> None:
    backend, spi, _cs = _make_backend()
    frame = MatrixFrame.blank(32, 16)
    frame.data[0] = 64
    frame.data[1] = 128
    spi.writes.clear()

    assert backend.write_frame(frame, allow_lossy=False) is False
    assert not spi.writes

    assert backend.write_frame(frame, allow_lossy=True) is True
    assert set(_intensity_writes(spi.writes)) == {8}


def test_rgb_requires_the_lossy_override() -> None:
    backend, spi, _cs = _make_backend()
    frame = MatrixFrame.blank(32, 16, 3)
    frame.data[0:3] = bytearray((0, 5, 0))
    spi.writes.clear()

    assert backend.write_frame(frame, allow_lossy=False) is False
    assert not spi.writes

    assert backend.write_frame(frame, allow_lossy=True) is True
    assert (0, 0) in _decode(spi.writes)


@pytest.mark.parametrize(
    "frame",
    [
        MatrixFrame.blank(16, 16),  # too narrow
        MatrixFrame.blank(32, 8),  # too short
        Frame(16, 16),  # packed, too narrow
    ],
)
def test_frames_not_fitted_to_hardware_geometry_are_refused(frame: object) -> None:
    backend, spi, _cs = _make_backend()
    spi.writes.clear()

    assert backend.write_frame(frame, allow_lossy=True) is False
    assert not spi.writes


def test_clear_blanks_the_framebuffer_and_reapplies_config() -> None:
    backend, spi, _cs = _make_backend()
    state = _MatrixState()
    frame = MatrixFrame.blank(32, 16)
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


def test_flip_rotates_the_whole_surface_swapping_panels() -> None:
    backend, spi, _cs = _make_backend()
    state = _MatrixState()
    frame = MatrixFrame.blank(32, 16)
    lit_in = {(0, 0), (31, 0), (5, 2), (10, 9)}
    for x, y in lit_in:
        frame.data[y * frame.width + x] = 15
    assert backend.write_frame(frame, allow_lossy=False) is True
    state.apply(spi.writes)
    assert state.lit() == lit_in

    backend.flip()

    state.apply(spi.writes)
    assert state.lit() == {(_WIDTH - 1 - x, _HEIGHT - 1 - y) for x, y in lit_in}
    # (5, 2) started in the top panel and must land in the bottom one.
    assert (26, 13) in state.lit()


def test_flip_rotates_packed_frames_through_the_fast_path() -> None:
    backend, spi, _cs = _make_backend()
    state = _MatrixState()
    frame = Frame(32, 16, intensity=255)
    lit_in = {(0, 0), (3, 1), (20, 10), (31, 15)}
    for x, y in lit_in:
        frame.pixel(x, y)
    assert backend.write_frame(frame, allow_lossy=False) is True
    state.apply(spi.writes)
    assert state.lit() == lit_in

    backend.flip()

    state.apply(spi.writes)
    assert state.lit() == {(_WIDTH - 1 - x, _HEIGHT - 1 - y) for x, y in lit_in}


def _make_facade(*, brightness: float = 1.0) -> MAX7219:
    """Build the public facade over the machine SPI stub."""
    return MAX7219(spi_id=1, sck=26, mosi=27, cs=28, brightness=brightness)


def _make_backend() -> tuple[_MAX7219Backend, FakeSPI, FakeCS]:
    """Build a backend with local SPI/CS fakes."""
    spi, cs = FakeSPI(), FakeCS()
    return _MAX7219Backend(spi, cs), spi, cs


def _row_writes(writes: list[bytes]) -> list[bytes]:
    """Return only digit-register row writes."""
    return [write for write in writes if 1 <= write[0] <= _PANEL_H]


def _intensity_writes(writes: list[bytes]) -> list[int]:
    """Return the values written to the intensity register, in order."""
    return [write[1] for write in writes if write[0] == _REG_INTENSITY]


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
    """Reconstruct lit visual pixels from MAX7219 SPI frames.

    Independent restatement of the panel wiring: eight chips are written
    last-first, chips 0-3 form the top panel and 4-7 the bottom, each chip owns
    an 8-pixel column block with bit 0 leftmost, and digit register N drives
    visual row ``8 - N`` within its panel.
    """
    lit: set[tuple[int, int]] = set()
    for frame in writes:
        reg = frame[0]
        if not 1 <= reg <= _PANEL_H:
            continue
        for pos in range(_NUM_CHIPS):
            data = frame[pos * 2 + 1]
            chip = _NUM_CHIPS - 1 - pos
            panel, col_chip = divmod(chip, 4)
            vy = panel * _PANEL_H + (_PANEL_H - reg)
            for bit in range(8):
                if data & (1 << bit):
                    lit.add((col_chip * 8 + bit, vy))
    return lit


@pytest.fixture(autouse=True)
def _reset_machine() -> None:
    """Clear machine stub state around each case."""
    machine.reset()
