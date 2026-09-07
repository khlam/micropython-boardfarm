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


@pytest.mark.parametrize("packed", [False, True])
def test_exact_size_frames_reach_the_backend_unchanged(*, packed: bool) -> None:
    backend = _Backend()
    display = Display(backend, width_pixels=4, height_pixels=2)
    source = Frame(4, 2, intensity=255)
    source.pixel(0, 0)
    if not packed:
        source = source.unpack()

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
    assert frame.data is source.data
    assert source.intensity == 255


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

    # Odd spare space goes to the right/bottom: 0px left margin and 1px top margin.
    display.show(_matrix([[1.0, 1.0]]))

    frame, _allow_lossy = backend.writes[-1]
    assert frame.value_at(0, 0) == 0
    assert frame.value_at(0, 1) == 255
    assert frame.value_at(3, 2) == 255
    assert frame.value_at(4, 2) == 0


def test_rgb_fitting_and_brightness_preserve_channels_and_source_data() -> None:
    backend = _Backend()
    display = Display(backend, width_pixels=5, height_pixels=2, brightness=0.5)
    source = MatrixFrame(2, 1, 3, bytearray((0, 1, 255, 32, 64, 128)))

    display.show(source)

    frame, _allow_lossy = backend.writes[-1]
    assert frame.channels == 3
    assert list(frame.data) == [0, 1, 128, 0, 1, 128, 16, 32, 64, 16, 32, 64, 0, 0, 0] * 2
    assert source.data == bytearray((0, 1, 255, 32, 64, 128))


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


@pytest.mark.parametrize("failure_accepted", [True, False])
def test_backend_rejection_tries_the_marker_then_clears_if_rejected(
    *, failure_accepted: bool
) -> None:
    backend = _Backend(results=(False, failure_accepted))
    display = Display(backend, width_pixels=6, height_pixels=7, brightness=0.25)

    display.show(_matrix([[1.0]]))

    assert len(backend.writes) == 2
    failure, allow_lossy = backend.writes[-1]
    assert allow_lossy is True
    assert _lit_pixels(failure) == {(0, 0), (5, 0), (0, 6), (5, 6)}
    assert failure.intensity == 64
    assert backend.clears == int(not failure_accepted)


@pytest.mark.parametrize("width,height", [(1, 4), (4, 1)])
def test_failure_clears_when_either_axis_is_too_small_for_a_marker(width: int, height: int) -> None:
    backend = _Backend(results=(False,))
    display = Display(backend, width_pixels=width, height_pixels=height)

    display.show(_matrix([[1.0]]))

    assert len(backend.writes) == 1
    assert backend.clears == 1


@pytest.mark.parametrize("packed", [False, True])
@pytest.mark.parametrize(
    "width,height,expected",
    [
        (8, 4, {(0, 1), (1, 2)}),
        (4, 8, {(1, 0), (2, 1)}),
        # Aspect ratios match exactly, so neither axis dominates and the frame
        # fills the display edge to edge with no centering margin.
        (8, 8, {(0, 0), (1, 1)}),
    ],
)
def test_lossy_downscale_samples_pixels_and_centers_with_preserved_aspect(
    *, packed: bool, width: int, height: int, expected: set[tuple[int, int]]
) -> None:
    backend = _Backend()
    display = Display(backend, width_pixels=4, height_pixels=4, allow_lossy=True)
    source = Frame(width, height, intensity=128)
    for x, y in ((0, 0), (2, 2), (1, 0)):
        source.pixel(x, y)

    display.show(source if packed else source.unpack())

    frame, allow_lossy = backend.writes[-1]
    assert allow_lossy is True
    assert (frame.width, frame.height) == (4, 4)
    assert _lit_pixels(frame) == expected
    assert {value for value in frame.data if value} == {128}


@pytest.mark.parametrize("width,height", [(100, 1), (1, 100)])
def test_lossy_downscale_retains_one_pixel_for_extreme_aspect_ratios(
    width: int, height: int
) -> None:
    backend = _Backend()
    display = Display(backend, width_pixels=4, height_pixels=4, allow_lossy=True)

    display.show(MatrixFrame(width, height, 1, bytearray([255]) * width * height))

    frame, _allow_lossy = backend.writes[-1]
    expected = {(x, 1) for x in range(4)} if width > height else {(1, y) for y in range(4)}
    assert _lit_pixels(frame) == expected


@pytest.mark.parametrize(
    "brightness,expected",
    [
        (-0.5, 0),  # below range clamps to fully off
        (0.0, 0),
        (0.5, 128),
        (0.0001, 1),  # positive brightness must preserve lit pixels
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


class _Backend:
    """Display backend fake recording frames, clears, and flips."""

    def __init__(self, *, results: tuple[bool, ...] = (True,)) -> None:
        """Initialise the call log."""
        self.results = results
        self.writes: list[tuple[object, bool]] = []
        self.clears = 0
        self.flips = 0

    def write_frame(self, frame: object, *, allow_lossy: bool) -> bool:
        """Record one frame write and return the configured result."""
        self.writes.append((frame, allow_lossy))
        return self.results[min(len(self.writes) - 1, len(self.results) - 1)]

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
