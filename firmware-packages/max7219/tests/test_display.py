"""Host CPython tests for the MAX7219 pixel-display backend.

Covers the chain wiring (which SPI frame lights which visual pixel), the
dirty-row and intensity write policy, geometry refusal, and the 180-degree
flip. The decoder below deliberately restates the panel layout from
the hardware wiring rather than importing the driver's ``_FLIP_Y``/``_MIRROR_X``
constants, so an orientation regression fails here instead of flipping encoder
and decoder in lockstep.
"""

from __future__ import annotations

import machine
import pytest
import utime
from fake_max7219 import FakeCS, FakeSPI

from max7219 import MAX7219
from max7219.max7219 import (
    _PANEL_H,
    _REG_DISPLAY_TEST,
    _REG_INTENSITY,
    _REG_SHUTDOWN,
    _MAX7219Backend,
)
from pixel_frame import Frame

_NUM_CHIPS = 8
_WIDTH = 32
_HEIGHT = 16


def test_facade_opens_declared_geometry_and_spi_bus_settings() -> None:
    display = _make_facade()
    spi = machine.SPI.instances[-1]

    assert (display.width_pixels, display.height_pixels) == (32, 16)
    assert (spi.id, spi.sck.id, spi.mosi.id) == (1, 26, 27)
    assert spi.baudrate == 1_000_000
    assert (spi.polarity, spi.phase) == (0, 0)


def test_facade_idles_chip_select_high_on_the_requested_pin() -> None:
    """CS must be an output already high: the chain latches on the rising edge."""
    _make_facade()

    cs_pins = [pin for pin in machine.Pin.instances if pin.id == 28]

    assert len(cs_pins) == 1
    assert cs_pins[0].mode == machine.Pin.OUT
    assert cs_pins[0].value() == 1


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


@pytest.mark.parametrize("y,chain_position", [(0, 7), (8, 3)])
def test_leftmost_pixel_lands_on_its_documented_panel_chain_bytes(
    y: int, chain_position: int
) -> None:
    backend, spi, _cs = _make_backend()
    frame = Frame(32, 16, intensity=255)
    frame.pixel(0, y)
    spi.writes.clear()

    assert backend.write_frame(frame) is True

    # Both panel origins use digit 8; last-chip-first wiring places them four words apart.
    row = _row_writes(spi.writes)[0]
    assert row == b"\x08\x00" * chain_position + b"\x08\x01" + b"\x08\x00" * (7 - chain_position)


def test_init_flashes_then_configures_and_clears_every_chip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delays = []
    monkeypatch.setattr(utime, "sleep_ms", delays.append)
    _backend, spi, cs = _make_backend()

    assert delays == [250]
    commands = [(15, 1), (15, 0), (11, 7), (9, 0), (12, 1), (10, 0)]
    commands.extend((row, 0) for row in range(1, 9))
    assert spi.writes == [bytes((register, value)) * 8 for register, value in commands]
    assert cs.toggles == ["off", "on"] * len(spi.writes)


def test_frame_padding_is_not_rendered_on_either_panel() -> None:
    backend, spi, _cs = _make_backend()
    frame = Frame.from_packed(32, 16, 6, bytearray((0, 0, 0, 0, 255, 255)) * 16)
    corners = {(0, 0), (31, 0), (0, 15), (31, 15), (5, 9)}
    for x, y in corners:
        frame.pixel(x, y)
    spi.writes.clear()

    assert backend.write_frame(frame) is True

    assert _decode(spi.writes) == corners


def test_changed_frames_refresh_only_dirty_rows_without_static_config() -> None:
    backend, spi, _cs = _make_backend()
    frame = Frame(32, 16, intensity=128)
    frame.pixel(0, 0)
    spi.writes.clear()

    assert backend.write_frame(frame) is True

    regs = [write[0] for write in spi.writes]
    assert _REG_DISPLAY_TEST not in regs
    assert _REG_SHUTDOWN not in regs
    assert _intensity_writes(spi.writes)[-1] == 8
    assert len(_row_writes(spi.writes)) == 1
    assert _decode(spi.writes) == {(0, 0)}

    frame.pixel(1, 0)
    spi.writes.clear()

    assert backend.write_frame(frame) is True
    assert len(_row_writes(spi.writes)) == 1
    assert _decode(spi.writes) == {(0, 0), (1, 0)}


@pytest.mark.parametrize("intensity,register", [(8, 0), (9, 1), (246, 14)])
def test_same_bitmap_with_lower_brightness_writes_only_intensity(
    intensity: int, register: int
) -> None:
    backend, spi, _cs = _make_backend()
    state = _MatrixState()
    bright = Frame(32, 16, intensity=255)
    bright.pixel(0, 0)
    assert backend.write_frame(bright) is True
    state.apply(spi.writes)

    dim = Frame.from_packed(bright.width, bright.height, bright.stride, bright.data, intensity)
    spi.writes.clear()

    assert backend.write_frame(dim) is True

    state.apply(spi.writes)
    assert _intensity_writes(spi.writes) == [register]
    assert not _row_writes(spi.writes)  # same bitmap, only brightness moved
    assert state.lit() == {(0, 0)}


def test_zero_intensity_packed_frame_blanks_the_matrix() -> None:
    backend, spi, _cs = _make_backend()
    lit = Frame(32, 16, intensity=255)
    lit.pixel(4, 4)
    assert backend.write_frame(lit) is True
    state = _MatrixState()
    state.apply(spi.writes)
    spi.writes.clear()

    dark = Frame(32, 16, intensity=0)
    dark.pixel(4, 4)
    assert backend.write_frame(dark) is True

    state.apply(spi.writes)
    assert not state.lit()


def test_unchanged_frame_reasserts_config_and_all_rows() -> None:
    backend, spi, _cs = _make_backend()
    frame = Frame(32, 16, intensity=64)
    frame.pixel(0, 0)
    assert backend.write_frame(frame) is True
    spi.writes.clear()

    assert backend.write_frame(frame) is True

    regs = [write[0] for write in spi.writes]
    assert _REG_DISPLAY_TEST in regs
    assert _REG_SHUTDOWN in regs
    assert _intensity_writes(spi.writes) == [4]
    assert len(_row_writes(spi.writes)) == _PANEL_H


@pytest.mark.parametrize("width,height", [(16, 16), (32, 8), (64, 16), (32, 32)])
def test_frames_not_fitted_to_hardware_geometry_are_refused(width: int, height: int) -> None:
    backend, spi, _cs = _make_backend()
    spi.writes.clear()

    assert backend.write_frame(Frame(width, height)) is False
    assert not spi.writes


def test_clear_blanks_the_framebuffer_and_reapplies_config() -> None:
    backend, spi, _cs = _make_backend()
    state = _MatrixState()
    frame = Frame(32, 16, intensity=255)
    frame.pixel(0, 0)
    backend.write_frame(frame)
    state.apply(spi.writes)
    spi.writes.clear()

    backend.clear()

    state.apply(spi.writes)
    regs = [write[0] for write in spi.writes]
    assert _REG_DISPLAY_TEST in regs
    assert _REG_SHUTDOWN in regs
    assert len(_row_writes(spi.writes)) == _PANEL_H
    assert not state.lit()


def test_flip_swaps_panels_and_a_second_flip_restores_the_image() -> None:
    backend, spi, _cs = _make_backend()
    state = _MatrixState()
    frame = Frame(32, 16, intensity=128)
    lit_in = {(0, 0), (31, 0), (5, 2), (10, 9)}
    for x, y in lit_in:
        frame.pixel(x, y)
    assert backend.write_frame(frame) is True
    state.apply(spi.writes)
    assert state.lit() == lit_in
    spi.writes.clear()

    backend.flip()

    state.apply(spi.writes)
    assert state.lit() == {(_WIDTH - 1 - x, _HEIGHT - 1 - y) for x, y in lit_in}
    assert not _intensity_writes(spi.writes)
    spi.writes.clear()

    backend.flip()

    state.apply(spi.writes)
    assert state.lit() == lit_in


def test_flip_before_the_first_frame_sets_orientation_without_writing() -> None:
    backend, spi, _cs = _make_backend()
    spi.writes.clear()

    backend.flip()

    assert not spi.writes
    frame = Frame(32, 16)
    frame.pixel(0, 0)
    assert backend.write_frame(frame) is True
    assert _decode(spi.writes) == {(31, 15)}


def test_rejected_conversion_preserves_the_last_frame_and_recovers_on_next_write() -> None:
    backend, spi, _cs = _make_backend()
    state = _MatrixState()
    initial = Frame(32, 16, intensity=128)
    initial.pixel(5, 2)
    assert backend.write_frame(initial) is True
    state.apply(spi.writes)
    spi.writes.clear()

    assert backend.write_frame(Frame(16, 16)) is False

    assert not spi.writes
    backend.flip()
    state.apply(spi.writes)
    assert state.lit() == {(26, 13)}
    spi.writes.clear()

    assert backend.write_frame(Frame(32, 16)) is True

    state.apply(spi.writes)
    assert not state.lit()


def test_spi_failures_propagate_to_the_caller(monkeypatch: pytest.MonkeyPatch) -> None:
    backend, spi, _cs = _make_backend()
    frame = Frame(32, 16)
    frame.pixel(0, 0)

    def fail_write(_buf: bytes) -> None:
        raise OSError("SPI unavailable")

    monkeypatch.setattr(spi, "write", fail_write)

    with pytest.raises(OSError, match="SPI unavailable"):
        backend.write_frame(frame)


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
