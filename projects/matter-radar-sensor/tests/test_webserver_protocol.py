"""HTTP and WebSocket input limits, admission rates, and failure classes."""

import errno
from contextlib import nullcontext as returns

import pytest

_KEY = "dGhlIHNhbXBsZSBub25jZQ=="
_UPGRADE = {
    "Upgrade": "websocket",
    "Connection": "keep-alive, Upgrade",
    "Sec-WebSocket-Key": _KEY,
    "Sec-WebSocket-Version": "13",
}


def _rejects(message):
    """Expect the ValueError a malformed input raises, naming its rule."""
    return pytest.raises(ValueError, match=message)


@pytest.mark.parametrize(
    ("line", "outcome"),
    [
        (b"GET / HTTP/1.1\r\n", returns()),
        (b"GET /ws?takeover=1 HTTP/1.0\r\n", returns()),
        (b"GET / HTTP/1.1\n", _rejects("invalid header line")),
        (b"GET HTTP/1.1\r\n", _rejects("invalid request line")),
        (b"GET relative HTTP/1.1\r\n", _rejects("invalid request line")),
        (b" / HTTP/1.1\r\n", _rejects("invalid request line")),
        (b"GET  / HTTP/1.1\r\n", _rejects("invalid request line")),
        (b"GET / HTTP/2\r\n", _rejects("invalid request line")),
    ],
)
def test_request_line(web, line, outcome):
    with outcome:
        web.check_request_line(line)


@pytest.mark.parametrize(
    ("line", "seen", "outcome"),
    [
        (b"Host: board\r\n", set(), returns(b"host")),
        (b"X-Custom_Header: value\r\n", set(), returns(b"x-custom_header")),
        (b"Content-Length: 0\r\n", set(), returns(b"content-length")),
        (b"Content-Length:  000 \r\n", set(), returns(b"content-length")),
        (b"Host: board\n", set(), _rejects("invalid header line")),
        (b"Host board\r\n", set(), _rejects("invalid or duplicate")),
        (b": board\r\n", set(), _rejects("invalid or duplicate")),
        (b" Host: board\r\n", set(), _rejects("invalid or duplicate")),
        (b"Host : board\r\n", set(), _rejects("invalid or duplicate")),
        (b"host: again\r\n", {b"host"}, _rejects("invalid or duplicate")),
        (b"HOST: again\r\n", {b"host"}, _rejects("invalid or duplicate")),
        (b"Content-Length: 1\r\n", set(), _rejects("bodies are unsupported")),
        (b"Content-Length: -1\r\n", set(), _rejects("bodies are unsupported")),
        (b"Content-Length:\r\n", set(), _rejects("bodies are unsupported")),
        (b"Transfer-Encoding: chunked\r\n", set(), _rejects("bodies are unsupported")),
    ],
)
def test_header_line(web, line, seen, outcome):
    with outcome as name:
        assert web.check_header_line(line, seen) == name


@pytest.mark.parametrize(
    ("changes", "valid"),
    [
        ({}, True),
        ({"Upgrade": "h2c"}, False),
        ({"Connection": "notupgrade"}, False),
        ({"Sec-WebSocket-Version": "12"}, False),
        ({"Sec-WebSocket-Key": "invalid"}, False),
        ({"Sec-WebSocket-Key": "!" * 24}, False),
        ({"Sec-WebSocket-Key": "YQ" + "=" * 22}, False),
        ({"Sec-WebSocket-Key": _KEY[:-2] + "Q="}, False),
        # 21 data characters cannot be base64, so decoding raises.
        ({"Sec-WebSocket-Key": "A" * 21 + "==="}, False),
        ({"Sec-WebSocket-Key": None}, False),
    ],
)
def test_valid_upgrade(web, changes, valid):
    """A None value removes that header."""
    headers = {**_UPGRADE, **changes}
    headers = {name: value for name, value in headers.items() if value is not None}
    assert web.valid_upgrade(headers) is valid


@pytest.mark.parametrize(
    ("header", "outcome"),
    [
        (b"\x88\x80", returns()),  # close, empty
        (b"\x88\xfd", returns()),  # close, 125 bytes
        (b"\x89\x80", returns()),  # ping, empty
        (b"\x89\xfd", returns()),  # ping, 125 bytes
        (b"\x8a\x80", returns()),  # pong, empty
        (b"\x8a\xfd", returns()),  # pong, 125 bytes
        (b"\x81\x80", _rejects("unsupported WebSocket frame")),  # text
        (b"\x82\xfd", _rejects("unsupported WebSocket frame")),  # binary
        (b"\x80\x80", _rejects("unsupported WebSocket frame")),  # continuation
        (b"\x09\x80", _rejects("unsupported WebSocket frame")),  # fragmented ping
        (b"\xc9\x80", _rejects("unsupported WebSocket frame")),  # reserved bit
        (b"\x8b\x80", _rejects("unsupported WebSocket frame")),  # reserved opcode
        (b"\x89\x00", _rejects("unsupported WebSocket frame")),  # unmasked
        (b"\x89\xfe", _rejects("unsupported WebSocket frame")),  # 16-bit length
        (b"\x89\xff", _rejects("unsupported WebSocket frame")),  # 64-bit length
    ],
)
def test_control_header(web, header, outcome):
    with outcome:
        web.check_control_header(header)


@pytest.mark.parametrize(
    ("payload", "outcome"),
    [
        (b"", returns()),
        (b"\x03\xe8", returns()),  # 1000
        (b"\x03\xe8bye", returns()),
        (b"\x0b\xb8", returns()),  # 3000 opens the registered range
        (b"\x13\x87", returns()),  # 4999 closes the private range
        (b"\x03\xf3\xc3\xa9", returns()),  # 1011 with a two-byte UTF-8 reason
        (b"\x03", _rejects("invalid close payload")),  # half a code
        (b"\x00\x01", _rejects("invalid close code")),  # unassigned code
        (b"\x03\xed", _rejects("invalid close code")),  # 1005 is reserved for "no status"
        (b"\x13\x88", _rejects("invalid close code")),  # 5000 is outside the private range
        (b"\x03\xe8\xff", _rejects("can't decode")),  # invalid UTF-8 reason
    ],
)
def test_close_payload(web, payload, outcome):
    with outcome:
        web.check_close_payload(payload)


@pytest.mark.parametrize(
    ("tokens", "token_ms", "now_ms", "period_ms", "expected"),
    [
        (0, 0, 249, 250, (0, 0)),
        (0, 0, 250, 250, (1, 250)),
        (0, 0, 749, 250, (2, 500)),
        (3, 0, 10_000, 250, (4, 10_000)),
        # A negative anchor sits that far before the tick counter wraps.
        (0, -100, 400, 500, (1, 400)),
    ],
)
def test_token_bucket_refills_whole_periods_up_to_the_cap(
    web, firmware_module, tokens, token_ms, now_ms, period_ms, expected
):
    token_ms %= firmware_module.time._PERIOD

    assert web.refill_tokens(tokens, token_ms, now_ms, period_ms) == expected


@pytest.mark.parametrize(
    ("exception", "reason"),
    [
        (MemoryError(), "memory"),
        (OSError(errno.ENOMEM), "socket"),
        (OSError(errno.ENOBUFS), "socket"),
        (OSError(23), "socket"),
        (OSError(24), "socket"),
        (OSError(errno.ECONNRESET), None),
        (OSError(), None),
        (ValueError(), None),
    ],
)
def test_only_memory_and_descriptor_exhaustion_are_resource_failures(web, exception, reason):
    assert web.resource_failure(exception) == reason


@pytest.fixture
def web(firmware_module):
    return firmware_module("webserver")
