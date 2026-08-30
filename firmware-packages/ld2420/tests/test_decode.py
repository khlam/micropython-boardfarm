"""Host tests for the LD2420 pure decode functions: no UART, no async."""

from ld2420.ld2420 import Target, _ack_frame_end, _decode_targets, _u16


def test_u16_little_endian():
    assert _u16(bytes([0x34, 0x12]), 0) == 0x1234


def test_decode_targets_absent_presence_byte_returns_empty_tuple(build_report):
    assert _decode_targets(build_report(present=False, distance_cm=145)) == ()


def test_decode_targets_converts_centimetres_to_millimetres(build_report):
    assert _decode_targets(build_report(distance_cm=145)) == (Target(1450),)


def test_decode_targets_reads_a_two_byte_little_endian_distance(build_report):
    assert _decode_targets(build_report(distance_cm=0x0123)) == (Target(0x0123 * 10),)


def test_decode_targets_zero_distance_still_reports_a_target(build_report):
    """Presence, not distance, decides whether the radar saw somebody."""
    assert _decode_targets(build_report(distance_cm=0)) == (Target(0),)


def test_ack_frame_end_returns_the_offset_past_a_complete_frame(build_ack):
    frame = build_ack(0x00FF)
    assert _ack_frame_end(bytearray(frame), 0) == len(frame)


def test_ack_frame_end_rejects_a_buffer_too_short_for_the_length_word(build_ack):
    frame = build_ack(0x00FF)
    assert _ack_frame_end(bytearray(frame[:5]), 0) is None


def test_ack_frame_end_rejects_a_body_shorter_than_a_status_reply(build_ack):
    frame = bytearray(build_ack(0x00FF))
    frame[4] = 3  # below _ACK_BODY_MINIMUM: too small to hold echo + status
    assert _ack_frame_end(frame, 0) is None


def test_ack_frame_end_rejects_a_truncated_frame(build_ack):
    frame = build_ack(0x00FF)
    assert _ack_frame_end(bytearray(frame[:-1]), 0) is None


def test_ack_frame_end_rejects_a_wrong_footer(build_ack):
    frame = bytearray(build_ack(0x00FF))
    frame[-1] ^= 0xFF
    assert _ack_frame_end(frame, 0) is None
