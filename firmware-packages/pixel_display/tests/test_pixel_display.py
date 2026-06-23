"""Host CPython tests for universal pixel display frames and fitting."""

from __future__ import annotations

import pytest

from pixel_display import Display, Frame


class _Backend:
    """Display backend fake recording frames and clear calls."""

    def __init__(self, *, result: bool = True) -> None:
        """Initialise the call log."""
        self.result = result
        self.writes: list[tuple[Frame, bool]] = []
        self.clears = 0

    def write_frame(self, frame: Frame, *, allow_lossy: bool) -> bool:
        """Record one frame write and return the configured result."""
        self.writes.append((frame, allow_lossy))
        return self.result

    def clear(self) -> None:
        """Record a clear request."""
        self.clears += 1


def test_from_matrix_quantizes_and_clamps_scalars() -> None:
    frame = Frame.from_matrix([[0.0, 0.5, 1.0, 2.0, -1.0]])

    assert (frame.width, frame.height, frame.channels) == (5, 1, 1)
    assert list(frame.data) == [0, 128, 255, 255, 0]


def test_from_matrix_accepts_channel_pixels() -> None:
    frame = Frame.from_matrix([[(1.0, 0.0, 0.0), (0.0, 0.5, 1.0)]])

    assert (frame.width, frame.height, frame.channels) == (2, 1, 3)
    assert list(frame.data) == [255, 0, 0, 0, 128, 255]


def test_from_matrix_rejects_empty_or_ragged_data() -> None:
    with pytest.raises(ValueError, match="at least one row"):
        Frame.from_matrix([])
    with pytest.raises(ValueError, match="same width"):
        Frame.from_matrix([[1.0], [1.0, 0.0]])
    with pytest.raises(ValueError, match="channel count"):
        Frame.from_matrix([[(1.0, 0.0), (1.0, 0.0, 0.0)]])


def test_text_helpers_render_non_empty_frames() -> None:
    text = Frame.text("8")
    number = Frame.number(42)
    lines = Frame.text_lines(("GPS", "WAIT"))

    assert (text.width, text.height, text.channels) == (5, 7, 1)
    assert any(text.data)
    assert any(number.data)
    assert lines.height == 16
    assert lines.width >= Frame.text("WAIT").width


def test_display_scales_small_frames_by_integer_blocks() -> None:
    backend = _Backend()
    display = Display(backend, width_pixels=6, height_pixels=6)

    display.show(Frame.from_matrix([[1.0, 0.0], [0.0, 1.0]]))

    frame, allow_lossy = backend.writes[-1]
    assert allow_lossy is False
    assert (frame.width, frame.height) == (6, 6)
    assert frame.value_at(0, 0) == 255
    assert frame.value_at(2, 2) == 255
    assert frame.value_at(3, 3) == 255
    assert frame.value_at(5, 5) == 255
    assert frame.value_at(3, 0) == 0


def test_display_centers_aspect_mismatched_frames() -> None:
    backend = _Backend()
    display = Display(backend, width_pixels=5, height_pixels=5)

    display.show(Frame.from_matrix([[1.0, 1.0]]))

    frame, _allow_lossy = backend.writes[-1]
    assert frame.value_at(0, 0) == 0
    assert frame.value_at(0, 1) == 255
    assert frame.value_at(3, 2) == 255
    assert frame.value_at(4, 2) == 0


def test_oversized_frame_renders_failure_without_lossy_default() -> None:
    backend = _Backend()
    display = Display(backend, width_pixels=2, height_pixels=2)

    display.show(Frame.from_matrix([[1.0, 1.0, 1.0]] * 3))

    frame, allow_lossy = backend.writes[-1]
    assert allow_lossy is True
    assert list(frame.data) == [255, 255, 255, 255]


def test_blank_failure_mode_clears_instead_of_marker() -> None:
    backend = _Backend()
    display = Display(backend, width_pixels=2, height_pixels=2, failure_mode="blank")

    display.show(Frame.from_matrix([[1.0, 1.0, 1.0]] * 3))

    assert not backend.writes
    assert backend.clears == 1


def test_allow_lossy_downscales_oversized_frames() -> None:
    backend = _Backend()
    display = Display(backend, width_pixels=2, height_pixels=2, allow_lossy=True)

    display.show(Frame.from_matrix([[1.0, 0.0, 0.0, 1.0]] * 4))

    frame, allow_lossy = backend.writes[-1]
    assert allow_lossy is True
    assert (frame.width, frame.height) == (2, 2)


def test_intensity_limit_caps_normalized_bytes() -> None:
    backend = _Backend()
    display = Display(
        backend,
        width_pixels=2,
        height_pixels=1,
        intensity_limit=0.5,
    )

    display.show(Frame.from_matrix([[0.0, 1.0]]))

    frame, _allow_lossy = backend.writes[-1]
    assert list(frame.data) == [0, 128]


def test_backend_failure_renders_configured_failure_frame() -> None:
    backend = _Backend(result=False)
    display = Display(backend, width_pixels=6, height_pixels=7)

    display.show(Frame.from_matrix([[1.0]]))

    assert len(backend.writes) == 2
    failure, allow_lossy = backend.writes[-1]
    assert allow_lossy is True
    assert any(failure.data)
