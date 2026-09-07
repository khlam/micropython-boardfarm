"""Host CPython tests for the pixel display facade.

Covers the three paths through ``Display.show``: the exact-geometry packed fast
path, matrix fitting (integer block scaling, centering, lossy downscale), and the
failure indicator. Frame primitives themselves are ``pixel_frame``'s concern; only
their interaction with fitting and brightness is exercised here.
"""

from __future__ import annotations

import pytest

from pixel_display import Display
from pixel_frame import Frame, MatrixFrame


def test_rejects_non_positive_geometry() -> None:
    with pytest.raises(ValueError, match="geometry must be positive"):
        Display(_Backend(), width_pixels=0, height_pixels=4)
    with pytest.raises(ValueError, match="geometry must be positive"):
        Display(_Backend(), width_pixels=4, height_pixels=-1)


def test_rejects_unknown_failure_mode() -> None:
    with pytest.raises(ValueError, match="failure_mode"):
        Display(_Backend(), width_pixels=4, height_pixels=4, failure_mode="explode")


def test_flip_delegates_to_backend_when_supported() -> None:
    backend = _Backend()
    Display(backend, width_pixels=4, height_pixels=4).flip()

    assert backend.flips == 1


def test_flip_is_a_no_op_for_backends_without_it() -> None:
    backend = _BackendWithoutFlip()

    # Must not raise: the flip capability is optional in the backend contract.
    Display(backend, width_pixels=4, height_pixels=4).flip()


def test_exact_size_packed_frames_reach_the_backend_unchanged() -> None:
    backend = _Backend()
    display = Display(backend, width_pixels=4, height_pixels=2)
    source = Frame(4, 2, intensity=255)
    source.pixel(0, 0)

    display.show(source)

    frame, allow_lossy = backend.writes[-1]
    assert allow_lossy is False
    assert frame is source  # brightness 1.0 -> no rescale, no copy


def test_brightness_rescales_packed_intensity_without_touching_bits() -> None:
    backend = _Backend()
    display = Display(backend, width_pixels=4, height_pixels=2, brightness=0.5)
    source = Frame(4, 2, intensity=255)
    source.pixel(0, 0)

    display.show(source)

    frame, _allow_lossy = backend.writes[-1]
    assert frame.intensity == 128
    assert frame.value_at(0, 0) == 128
    assert frame.value_at(1, 0) == 0


def test_undersized_packed_frames_unpack_and_scale_by_integer_blocks() -> None:
    backend = _Backend()
    display = Display(backend, width_pixels=4, height_pixels=2)
    source = Frame(2, 1)
    source.pixel(0, 0)

    display.show(source)

    frame, _allow_lossy = backend.writes[-1]
    assert isinstance(frame, MatrixFrame)
    assert (frame.width, frame.height) == (4, 2)
    # The single lit source pixel becomes a 2x2 block in the top-left.
    assert frame.value_at(0, 0) == 255
    assert frame.value_at(1, 1) == 255
    assert frame.value_at(2, 0) == 0


def test_matrix_frames_scale_by_integer_blocks() -> None:
    backend = _Backend()
    display = Display(backend, width_pixels=6, height_pixels=6)

    display.show(_matrix([[1.0, 0.0], [0.0, 1.0]]))

    frame, allow_lossy = backend.writes[-1]
    assert allow_lossy is False
    assert (frame.width, frame.height) == (6, 6)
    assert frame.value_at(0, 0) == 255
    assert frame.value_at(2, 2) == 255
    assert frame.value_at(3, 3) == 255
    assert frame.value_at(5, 5) == 255
    assert frame.value_at(3, 0) == 0


def test_aspect_mismatched_frames_are_centered() -> None:
    backend = _Backend()
    display = Display(backend, width_pixels=5, height_pixels=5)

    # A 2x1 source scales x2 to 4x2, leaving a 1px left margin and 1px top margin.
    display.show(_matrix([[1.0, 1.0]]))

    frame, _allow_lossy = backend.writes[-1]
    assert frame.value_at(0, 0) == 0
    assert frame.value_at(0, 1) == 255
    assert frame.value_at(3, 2) == 255
    assert frame.value_at(4, 2) == 0


def test_brightness_scales_matrix_bytes() -> None:
    backend = _Backend()
    display = Display(backend, width_pixels=2, height_pixels=1, brightness=0.5)

    display.show(_matrix([[0.0, 1.0]]))

    frame, _allow_lossy = backend.writes[-1]
    assert list(frame.data) == [0, 128]


def test_show_rejects_content_that_is_not_a_frame() -> None:
    display = Display(_Backend(), width_pixels=4, height_pixels=4)

    with pytest.raises(TypeError, match="Frame or MatrixFrame"):
        display.show([[1.0]])


def test_oversized_frames_render_the_corner_failure_marker() -> None:
    backend = _Backend()
    display = Display(backend, width_pixels=6, height_pixels=4)

    display.show(_matrix([[1.0] * 8] * 8))

    frame, allow_lossy = backend.writes[-1]
    assert allow_lossy is True
    # "corner_xs" means exactly the four corners are lit — nothing else.
    assert _lit_pixels(frame) == {(0, 0), (5, 0), (0, 3), (5, 3)}


def test_oversized_packed_frames_also_render_the_failure_marker() -> None:
    backend = _Backend()
    display = Display(backend, width_pixels=4, height_pixels=4)

    display.show(Frame(8, 8))

    frame, allow_lossy = backend.writes[-1]
    assert allow_lossy is True
    assert _lit_pixels(frame) == {(0, 0), (3, 0), (0, 3), (3, 3)}


def test_blank_failure_mode_clears_instead_of_drawing_a_marker() -> None:
    backend = _Backend()
    display = Display(backend, width_pixels=4, height_pixels=4, failure_mode="blank")

    display.show(_matrix([[1.0] * 8] * 8))

    assert not backend.writes
    assert backend.clears == 1


def test_backend_rejection_falls_back_to_the_failure_marker() -> None:
    backend = _Backend(result=False)
    display = Display(backend, width_pixels=6, height_pixels=7)

    display.show(_matrix([[1.0]]))

    assert len(backend.writes) == 2
    failure, allow_lossy = backend.writes[-1]
    assert allow_lossy is True
    assert _lit_pixels(failure) == {(0, 0), (5, 0), (0, 6), (5, 6)}


def test_backend_rejecting_the_failure_frame_clears_the_display() -> None:
    backend = _Backend(result=False)
    display = Display(backend, width_pixels=6, height_pixels=7)

    display.show(_matrix([[1.0]]))

    assert backend.clears == 1


def test_failure_clears_when_geometry_is_too_small_for_a_marker() -> None:
    backend = _Backend(result=False)
    display = Display(backend, width_pixels=1, height_pixels=1)

    display.show(_matrix([[1.0]]))

    # A 1x1 display cannot show four distinct corners, so it blanks instead.
    assert backend.clears == 1


def test_allow_lossy_downscales_oversized_frames_preserving_aspect() -> None:
    backend = _Backend()
    display = Display(backend, width_pixels=4, height_pixels=4, allow_lossy=True)

    # 8 wide x 4 tall is wider than the target's aspect, so width binds: 4x2.
    display.show(_matrix([[1.0] * 8] * 4))

    frame, allow_lossy = backend.writes[-1]
    assert allow_lossy is True
    assert (frame.width, frame.height) == (4, 4)
    assert _lit_rows(frame) == {1, 2}


def test_allow_lossy_downscale_binds_on_height_for_tall_frames() -> None:
    backend = _Backend()
    display = Display(backend, width_pixels=4, height_pixels=4, allow_lossy=True)

    # 4 wide x 8 tall is taller than the target's aspect, so height binds: 2x4.
    display.show(_matrix([[1.0] * 4] * 8))

    frame, _allow_lossy = backend.writes[-1]
    assert _lit_columns(frame) == {1, 2}


@pytest.mark.parametrize(
    "brightness,expected",
    [
        (-0.5, 0),  # below range clamps to fully off
        (0.0, 0),
        (0.5, 128),
        (1.5, 255),  # above range clamps to full brightness
    ],
)
def test_brightness_is_clamped_to_the_normalized_range(brightness: float, expected: int) -> None:
    backend = _Backend()
    display = Display(backend, width_pixels=1, height_pixels=1, brightness=brightness)

    display.show(_matrix([[1.0]]))

    frame, _allow_lossy = backend.writes[-1]
    assert frame.value_at(0, 0) == expected


def _matrix(rows: list) -> MatrixFrame:
    """Build a MatrixFrame from rows of normalized scalars or channel tuples."""
    height = len(rows)
    width = len(rows[0])
    channels = len(rows[0][0]) if isinstance(rows[0][0], (list, tuple)) else 1
    data = bytearray()
    for row in rows:
        for pixel in row:
            values = pixel if channels > 1 else (pixel,)
            for value in values:
                data.append(min(255, max(0, int(value * 255 + 0.5))))
    return MatrixFrame(width, height, channels, data)


def _lit_pixels(frame: object) -> set:
    """Return the ``(x, y)`` coordinates of every non-zero pixel."""
    return {
        (x, y) for y in range(frame.height) for x in range(frame.width) if frame.value_at(x, y) != 0
    }


def _lit_rows(frame: object) -> set:
    """Return the row indexes containing at least one lit pixel."""
    return {y for _x, y in _lit_pixels(frame)}


def _lit_columns(frame: object) -> set:
    """Return the column indexes containing at least one lit pixel."""
    return {x for x, _y in _lit_pixels(frame)}


class _Backend:
    """Display backend fake recording frames, clears, and flips."""

    def __init__(self, *, result: bool = True) -> None:
        """Initialise the call log."""
        self.result = result
        self.writes: list[tuple[object, bool]] = []
        self.clears = 0
        self.flips = 0

    def write_frame(self, frame: object, *, allow_lossy: bool) -> bool:
        """Record one frame write and return the configured result."""
        self.writes.append((frame, allow_lossy))
        return self.result

    def clear(self) -> None:
        """Record a clear request."""
        self.clears += 1

    def flip(self) -> None:
        """Record a flip request."""
        self.flips += 1


class _BackendWithoutFlip:
    """Backend fake exercising the optional-flip half of the contract."""

    def write_frame(self, frame: object, *, allow_lossy: bool) -> bool:
        """Accept every frame."""
        return True

    def clear(self) -> None:
        """Accept a clear request."""
