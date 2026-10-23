"""Host CPython tests for the pixel display facade.

Covers the two paths through ``Display.show``: an exact-geometry packed frame
reaching the backend with brightness applied, and the corner-marker failure
indicator for everything else. Frame primitives themselves are ``pixel_frame``'s
concern; only their interaction with brightness is exercised here.
"""

from __future__ import annotations

import pytest

from pixel_display import Display
from pixel_frame import Frame


def test_rejects_non_positive_geometry() -> None:
    with pytest.raises(ValueError, match="geometry must be positive"):
        Display(_Backend(), width_pixels=0, height_pixels=4)
    with pytest.raises(ValueError, match="geometry must be positive"):
        Display(_Backend(), width_pixels=4, height_pixels=-1)


def test_flip_delegates_to_the_backend() -> None:
    backend = _Backend()
    Display(backend, width_pixels=4, height_pixels=4).flip()

    assert backend.flips == 1


def test_exact_size_frames_reach_the_backend_unchanged() -> None:
    backend = _Backend()
    display = Display(backend, width_pixels=4, height_pixels=2)
    source = Frame(4, 2, intensity=255)
    source.pixel(0, 0)

    display.show(source)

    assert backend.writes[-1] is source  # brightness 1.0 -> no rescale, no copy


def test_brightness_rescales_packed_intensity_without_touching_bits() -> None:
    backend = _Backend()
    display = Display(backend, width_pixels=4, height_pixels=2, brightness=0.5)
    source = Frame(4, 2, intensity=255)
    source.pixel(0, 0)

    display.show(source)

    frame = backend.writes[-1]
    assert frame.intensity == 128
    assert frame.value_at(0, 0) == 128
    assert frame.value_at(1, 0) == 0
    assert frame.data is source.data
    assert source.intensity == 255


def test_show_rejects_content_that_is_not_a_frame() -> None:
    display = Display(_Backend(), width_pixels=4, height_pixels=4)

    with pytest.raises(TypeError, match="Frame"):
        display.show([[1.0]])


@pytest.mark.parametrize("width,height", [(8, 8), (2, 1), (4, 8)])
def test_mismatched_geometry_renders_the_corner_failure_marker(width: int, height: int) -> None:
    backend = _Backend()
    display = Display(backend, width_pixels=4, height_pixels=4)

    display.show(Frame(width, height))

    # "corner_xs" means exactly the four corners are lit — nothing else.
    assert _lit_pixels(backend.writes[-1]) == {(0, 0), (3, 0), (0, 3), (3, 3)}


@pytest.mark.parametrize("failure_accepted", [True, False])
def test_backend_rejection_tries_the_marker_then_clears_if_rejected(
    *, failure_accepted: bool
) -> None:
    backend = _Backend(results=(False, failure_accepted))
    display = Display(backend, width_pixels=6, height_pixels=7, brightness=0.25)

    display.show(Frame(6, 7))

    assert len(backend.writes) == 2
    failure = backend.writes[-1]
    assert _lit_pixels(failure) == {(0, 0), (5, 0), (0, 6), (5, 6)}
    assert failure.intensity == 64
    assert backend.clears == int(not failure_accepted)


@pytest.mark.parametrize("width,height", [(1, 4), (4, 1)])
def test_failure_clears_when_either_axis_is_too_small_for_a_marker(width: int, height: int) -> None:
    backend = _Backend(results=(False,))
    display = Display(backend, width_pixels=width, height_pixels=height)

    display.show(Frame(width, height))

    assert len(backend.writes) == 1
    assert backend.clears == 1


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
    source = Frame(1, 1)
    source.pixel(0, 0)

    display.show(source)

    assert backend.writes[-1].value_at(0, 0) == expected


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
        self.writes: list[object] = []
        self.clears = 0
        self.flips = 0

    def write_frame(self, frame: object) -> bool:
        """Record one frame write and return the configured result."""
        self.writes.append(frame)
        return self.results[min(len(self.writes) - 1, len(self.results) - 1)]

    def clear(self) -> None:
        """Record a clear request."""
        self.clears += 1

    def flip(self) -> None:
        """Record a flip request."""
        self.flips += 1
