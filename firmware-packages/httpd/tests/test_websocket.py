import asyncio

import pytest

from httpd import Broadcast
from httpd import server as server_module
from httpd import websocket as websocket_module
from httpd.websocket import frame, upgrade_response

# The worked example from RFC 6455 section 1.3.
_RFC_KEY = "dGhlIHNhbXBsZSBub25jZQ=="
_RFC_ACCEPT = b"s3pPLMBiTxaQ9kYGzzhZRbK+xOo="

_HANDSHAKE = b"GET /ws HTTP/1.1\r\nUpgrade: websocket\r\nSec-WebSocket-Key: " + _RFC_KEY.encode()


def test_the_handshake_answers_with_the_key_the_rfc_derives():
    response = upgrade_response(_RFC_KEY)

    assert response.startswith(b"HTTP/1.1 101 Switching Protocols\r\n")
    assert b"Upgrade: websocket\r\n" in response
    assert b"Sec-WebSocket-Accept: " + _RFC_ACCEPT + b"\r\n" in response
    assert response.endswith(b"\r\n\r\n")


def test_a_short_payload_rides_in_the_header_length_byte():
    assert frame("hi") == b"\x81\x02hi"


def test_a_longer_payload_gets_the_sixteen_bit_length():
    payload = "x" * 200

    encoded = frame(payload)

    assert encoded[:2] == b"\x81\x7e"
    assert encoded[2:4] == (200).to_bytes(2, "big")
    assert encoded[4:] == payload.encode()


def test_the_boundary_between_the_two_length_forms_is_exact():
    assert frame("x" * 125)[:2] == b"\x81\x7d"
    assert frame("x" * 126)[:2] == b"\x81\x7e"


def test_a_payload_needing_a_sixty_four_bit_length_is_refused():
    with pytest.raises(ValueError, match="too long"):
        frame("x" * (websocket_module._MAX_PAYLOAD + 1))


def test_sending_with_no_clients_connected_does_nothing():
    Broadcast().send("dropped on the floor")


def test_a_payload_that_cannot_be_encoded_is_dropped_rather_than_raised():
    broadcast = Broadcast()
    client = _connect(broadcast)

    broadcast.send("\ud800")

    assert list(client._outbox) == []


def test_an_oversized_payload_is_dropped_rather_than_raised():
    broadcast = Broadcast()
    client = _connect(broadcast)

    broadcast.send("x" * (websocket_module._MAX_PAYLOAD + 1))

    assert list(client._outbox) == []


def test_one_framing_pass_is_shared_by_every_client():
    broadcast = Broadcast()
    first = _connect(broadcast)
    second = _connect(broadcast)

    broadcast.send("shared")

    assert first._outbox[0] is second._outbox[0]


def test_a_client_that_stops_reading_loses_its_oldest_frames():
    broadcast = Broadcast()
    client = _connect(broadcast)
    depth = websocket_module._OUTBOX_DEPTH

    for index in range(depth + 4):
        broadcast.send(str(index))

    assert len(client._outbox) == depth
    assert list(client._outbox) == [frame(str(index)) for index in range(4, depth + 4)]


def test_the_connection_ceiling_is_reported_before_it_is_exceeded():
    broadcast = Broadcast()

    for _ in range(websocket_module._MAX_CLIENTS):
        assert not broadcast.full()
        _connect(broadcast)

    assert broadcast.full()


def test_a_client_beyond_the_ceiling_is_told_the_stream_is_unavailable(server, serve):
    broadcast = server.stream("/ws")
    for _ in range(websocket_module._MAX_CLIENTS):
        _connect(broadcast)

    assert serve(server, _HANDSHAKE + b"\r\n\r\n") == server_module._UNAVAILABLE


@pytest.mark.parametrize(
    "request_bytes",
    [
        pytest.param(b"GET /ws HTTP/1.1\r\nUpgrade: websocket\r\n\r\n", id="no key"),
        pytest.param(
            b"GET /ws HTTP/1.1\r\nSec-WebSocket-Key: " + _RFC_KEY.encode() + b"\r\n\r\n",
            id="no upgrade header",
        ),
        pytest.param(
            b"GET /ws HTTP/1.1\r\nUpgrade: h2c\r\nSec-WebSocket-Key: "
            + _RFC_KEY.encode()
            + b"\r\n\r\n",
            id="upgrading to something else",
        ),
    ],
)
def test_an_incomplete_handshake_is_rejected(server, serve, request_bytes):
    server.stream("/ws")

    assert serve(server, request_bytes) == server_module._BAD_REQUEST


def test_a_stream_route_takes_priority_over_a_page_at_the_same_path(server, serve):
    server.page("/ws", b"never served")
    server.stream("/ws")

    assert serve(server, _HANDSHAKE + b"\r\n\r\n").startswith(b"HTTP/1.1 101 ")


def test_a_client_is_greeted_then_served_until_it_hangs_up(reader, writer):
    broadcast = Broadcast(greeting="hello")
    sink = writer()

    asyncio.run(broadcast.serve(reader(b""), sink))

    assert bytes(sink.buffer) == frame("hello")
    assert broadcast._clients == []


def test_whatever_a_client_sends_is_read_and_thrown_away(reader, writer):
    broadcast = Broadcast()
    sink = writer()

    asyncio.run(broadcast.serve(reader(b"\x81\x82\x01\x02\x03\x04hi\x88\x00"), sink))

    assert bytes(sink.buffer) == b""
    assert broadcast._clients == []


def test_a_client_connecting_without_a_greeting_is_sent_nothing_up_front(reader, writer):
    broadcast = Broadcast()
    sink = writer()

    asyncio.run(broadcast.serve(reader(b""), sink))

    assert bytes(sink.buffer) == b""


def test_close_retires_every_connected_client(reader, writer):
    broadcast = Broadcast()
    clients = [_connect(broadcast) for _ in range(2)]

    broadcast.close()

    assert all(client.closed for client in clients)


def test_a_write_failure_retires_the_client_rather_than_the_producer(reader, writer):
    broadcast = Broadcast(greeting="hello")
    sink = writer(fail_on_write=True)

    asyncio.run(broadcast.serve(reader(b""), sink))

    assert broadcast._clients == []


@pytest.mark.parametrize(
    ("frame_bytes", "keep_reading"),
    [
        pytest.param(b"\x81\x02hi", True, id="unmasked text"),
        pytest.param(b"\x81\x82\x01\x02\x03\x04hi", True, id="masked text"),
        pytest.param(
            b"\x81\xfe\x00\xc8" + b"\x01\x02\x03\x04" + b"z" * 200,
            True,
            id="masked sixteen bit length",
        ),
        pytest.param(b"\x88\x00", False, id="close"),
        pytest.param(b"\x81\x7f" + b"\x00" * 8, False, id="sixty four bit length"),
    ],
)
def test_client_input_is_discarded_until_the_connection_ends(
    reader, writer, frame_bytes, keep_reading
):
    client = websocket_module._Client(reader(frame_bytes), writer())

    assert asyncio.run(client._read_frame()) is keep_reading


def _connect(broadcast: Broadcast) -> object:
    """Attach one client to a broadcast without running its tasks.

    ``serve()`` owns the reader and writer for a client's whole lifetime, which
    is more machinery than a test of the fan-out itself needs. Registering the
    client directly leaves its outbox inspectable.

    Args:
        broadcast: The fan-out to attach to.

    Returns:
        The registered client.
    """
    client = websocket_module._Client(None, None)
    broadcast._clients.append(client)
    return client
