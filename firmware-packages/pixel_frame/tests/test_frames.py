"""Host CPython tests for the packed and matrix frame primitives.

``Frame`` is the packed monochrome buffer every screen renders into: bits are
row-major with a stride that may carry padding past ``width``, and one shared
byte intensity stands in for per-pixel brightness. The tests below pin the two
places that trips people up — padding must never surface through ``unpack`` or
``value_at``, and slice assignment is ``frame[y_slice, x_slice]`` in matrix
order, not ``(x, y)``.
"""

from __future__ import annotations

import pytest

from pixel_frame import Frame, MatrixFrame, Text


@pytest.mark.parametrize(
    "kwargs,message",
    [
        ({"width": 0}, "geometry must be positive"),
        ({"height": -1}, "geometry must be positive"),
        ({"stride": 1}, "stride is too small"),
        ({"data": bytearray(3)}, "data length does not match"),
    ],
)
def test_packed_frame_rejects_invalid_storage(kwargs: dict, message: str) -> None:
    config = {"width": 9, "height": 2, **kwargs}

    with pytest.raises(ValueError, match=message):
        Frame(**config)


@pytest.mark.parametrize(
    "width,height,channels,data,message",
    [
        (0, 2, 3, bytearray(), "geometry must be positive"),
        (2, -1, 3, bytearray(), "geometry must be positive"),
        (2, 2, 0, bytearray(), "geometry must be positive"),
        (2, 2, 3, bytearray(11), "data length does not match"),
    ],
)
def test_matrix_frame_rejects_invalid_storage(
    width: int, height: int, channels: int, data: bytearray, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        MatrixFrame(width, height, channels, data)


def test_packed_storage_uses_row_stride_and_excludes_padding_when_unpacked() -> None:
    data = bytearray((0x81, 0xFF, 0xFF, 0x02, 0xFE, 0xFF))
    frame = Frame.from_packed(9, 2, 3, data, intensity=37)

    frame.pixel(8, 1)
    frame.pixel(7, 0, on=False)

    assert frame.data is data
    assert data == bytearray((0x01, 0xFF, 0xFF, 0x02, 0xFF, 0xFF))
    unpacked = frame.unpack()
    assert (unpacked.width, unpacked.height, unpacked.channels) == (9, 2, 1)
    assert list(unpacked.data) == [37, 0, 0, 0, 0, 0, 0, 0, 37, 0, 37, 0, 0, 0, 0, 0, 0, 37]
    assert frame.value_at(8, 1) == 37
    assert frame.value_at(7, 0) == 0


def test_copy_and_unpack_own_storage_and_clear_includes_padding() -> None:
    source = Frame.from_packed(9, 1, 3, bytearray((1, 1, 255)), intensity=42)
    copied = source.copy()
    unpacked = source.unpack()

    copied.clear()
    unpacked.data[0] = 0

    assert (copied.width, copied.height, copied.stride, copied.intensity) == (9, 1, 3, 42)
    assert copied.data == bytearray(3)
    assert source.data == bytearray((1, 1, 255))
    assert source.value_at(0, 0) == 42


@pytest.mark.parametrize("x,y", [(-1, 0), (0, -1), (9, 0), (0, 2)])
def test_pixel_writes_clip_but_reads_reject_out_of_bounds(x: int, y: int) -> None:
    frame = Frame(9, 2)

    frame.pixel(x, y)

    assert frame.data == bytearray(4)
    with pytest.raises(IndexError, match="coordinate out of range"):
        frame.value_at(x, y)


def test_set_pixel_unchecked_skips_the_bounds_check_its_caller_already_did() -> None:
    """``Text`` draws through this to avoid re-checking every scaled sub-pixel.

    In-bounds it must match ``pixel``; out of bounds it is the caller's job, so a
    stray write corrupts a neighbouring row rather than being clipped away. That
    asymmetry is the whole reason the method exists, so it is pinned here.
    """
    frame = Frame(9, 2)

    frame.set_pixel_unchecked(8, 1)

    assert frame.value_at(8, 1) == 255
    frame.set_pixel_unchecked(8, 1, on=False)
    assert frame.value_at(8, 1) == 0

    # x=9 is past the width but inside the stride's padding byte, so it lands
    # in storage `pixel()` would have refused to touch.
    frame.set_pixel_unchecked(9, 0)
    assert frame.data[1] & 0b10 != 0


def test_packed_frames_reject_nonzero_channel_reads() -> None:
    with pytest.raises(IndexError, match="one channel"):
        Frame(1, 1).value_at(0, 0, channel=1)


@pytest.mark.parametrize("intensity,expected", [(-1, 0), (0, 0), (37, 37), (300, 255)])
def test_intensity_is_clamped_and_zero_intensity_unpacks_as_dark(
    intensity: int, expected: int
) -> None:
    frame = Frame(2, 1, intensity=intensity)
    frame.pixel(0, 0)

    assert frame.value_at(0, 0) == expected
    assert list(frame.unpack().data) == [expected, 0]
    assert frame.data == bytearray((1,))


def test_matrix_addresses_each_channel_of_a_pixel_in_row_major_order() -> None:
    data = bytearray(range(12))
    frame = MatrixFrame(2, 2, 3, data)

    assert frame.data is data
    assert [frame.value_at(0, 1, channel) for channel in range(3)] == [6, 7, 8]
    assert frame.value_at(1, 1, 2) == 11


@pytest.mark.parametrize(
    "key,error,message",
    [
        (slice(None), TypeError, "expects frame"),
        ((slice(None),), TypeError, "expects frame"),
        ((0, slice(None)), TypeError, "y index must be a slice"),
        ((slice(None), 0), TypeError, "x index must be a slice"),
        ((slice(None, None, 1), slice(None)), ValueError, "step is not supported"),
        ((slice(None), slice(0.5, 2)), TypeError, "bounds must be integers"),
        ((slice(-1, 3), slice(None)), ValueError, "negative indexes"),
        ((slice(0, -1), slice(None)), ValueError, "negative indexes"),
        ((slice(2, 2), slice(None)), ValueError, "must not be empty"),
        ((slice(3, 2), slice(None)), ValueError, "must not be empty"),
        ((slice(None), slice(0, 10)), ValueError, "exceeds frame bounds"),
    ],
)
def test_slice_assignment_rejects_invalid_boxes_without_drawing(
    key: object, error: type[Exception], message: str
) -> None:
    frame = Frame(9, 9)

    with pytest.raises(error, match=message):
        frame[key] = Text(1)

    assert not any(frame.data)


def test_slice_assignment_requires_drawable_content() -> None:
    frame = Frame(9, 9)

    with pytest.raises(TypeError, match="must expose draw"):
        frame[:, :] = "1"


def test_slice_assignment_uses_matrix_order_and_open_bounds() -> None:
    frame = Frame(9, 9)

    frame[2:, :1] = Text(":", scale=1)

    assert {(x, y) for y in range(9) for x in range(9) if frame.value_at(x, y)} == {
        (0, 4),
        (0, 6),
    }
