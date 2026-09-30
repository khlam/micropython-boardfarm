"""Host tests for the LD2420 decoder and ACK framing: no async."""

from collections.abc import Callable

from radar import LD2420, Target
from radar.ld2420 import _ack_frame_end


def test_decode_targets_absent_presence_byte_returns_empty_tuple(
    ld2420: LD2420, build_ld2420_report: Callable[..., bytes]
):
    """A report whose presence byte is clear decodes to no targets.

    Args:
        ld2420: The driver whose decoder is under test.
        build_ld2420_report: Encodes the report to decode.
    """
    assert ld2420._decode(build_ld2420_report(present=False, distance_cm=145)) == ()


def test_decode_targets_converts_centimetres_to_millimetres(
    ld2420: LD2420, build_ld2420_report: Callable[..., bytes]
):
    """The reported distance in centimetres decodes to a y in millimetres.

    Args:
        ld2420: The driver whose decoder is under test.
        build_ld2420_report: Encodes the report to decode.
    """
    assert ld2420._decode(build_ld2420_report(distance_cm=145)) == (Target(1, 0, 1450, 0, 0),)


def test_decode_targets_reads_a_two_byte_little_endian_distance(
    ld2420: LD2420, build_ld2420_report: Callable[..., bytes]
):
    """Both bytes of the distance field count, low byte first.

    Args:
        ld2420: The driver whose decoder is under test.
        build_ld2420_report: Encodes the report to decode.
    """
    assert ld2420._decode(build_ld2420_report(distance_cm=0x0123)) == (
        Target(1, 0, 0x0123 * 10, 0, 0),
    )


def test_decode_targets_zero_distance_still_reports_a_target(
    ld2420: LD2420, build_ld2420_report: Callable[..., bytes]
):
    """Presence, not distance, decides whether the ld2420 saw somebody.

    Args:
        ld2420: The driver whose decoder is under test.
        build_ld2420_report: Encodes the report to decode.
    """
    assert ld2420._decode(build_ld2420_report(distance_cm=0)) == (Target(1, 0, 0, 0, 0),)


def test_ack_frame_end_returns_the_offset_past_a_complete_frame(build_ack: Callable[..., bytes]):
    """A complete ACK frame ends at its own length.

    Args:
        build_ack: Encodes the ACK frame.
    """
    frame = build_ack(0x00FF)
    assert _ack_frame_end(bytearray(frame), 0) == len(frame)


def test_ack_frame_end_rejects_a_buffer_too_short_for_the_length_word(
    build_ack: Callable[..., bytes],
):
    """A buffer cut off before the length word isn't a frame yet.

    Args:
        build_ack: Encodes the ACK frame that is cut short.
    """
    frame = build_ack(0x00FF)
    assert _ack_frame_end(bytearray(frame[:5]), 0) is None


def test_ack_frame_end_rejects_a_body_shorter_than_a_status_reply(
    build_ack: Callable[..., bytes],
):
    """A length word too small to hold the echo and status isn't a frame.

    Args:
        build_ack: Encodes the ACK frame whose length word is shrunk.
    """
    frame = bytearray(build_ack(0x00FF))
    frame[4] = 3  # below _ACK_BODY_MINIMUM: too small to hold echo + status
    assert _ack_frame_end(frame, 0) is None


def test_ack_frame_end_rejects_a_truncated_frame(build_ack: Callable[..., bytes]):
    """A frame missing its last byte isn't complete.

    Args:
        build_ack: Encodes the ACK frame that is truncated.
    """
    frame = build_ack(0x00FF)
    assert _ack_frame_end(bytearray(frame[:-1]), 0) is None


def test_ack_frame_end_rejects_a_wrong_footer(build_ack: Callable[..., bytes]):
    """A frame with a corrupt footer isn't a frame.

    Args:
        build_ack: Encodes the ACK frame whose footer is corrupted.
    """
    frame = bytearray(build_ack(0x00FF))
    frame[-1] ^= 0xFF
    assert _ack_frame_end(frame, 0) is None
