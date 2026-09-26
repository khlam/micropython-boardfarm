"""HTTP and WebSocket input limits, admission rates, and failure classes."""

import errno

import pytest

_KEY = "dGhlIHNhbXBsZSBub25jZQ=="
_UPGRADE = {
    "Upgrade": "websocket",
    "Connection": "keep-alive, Upgrade",
    "Sec-WebSocket-Key": _KEY,
    "Sec-WebSocket-Version": "13",
}


@pytest.fixture
def web(firmware_module):
    return firmware_module("webserver")


@pytest.mark.parametrize(
    ("line", "valid"),
    [
        (b"GET / HTTP/1.1\r\n", True),
        (b"GET /ws?takeover=1 HTTP/1.0\r\n", True),
        (b"GET / HTTP/1.1\n", False),
        (b"GET / nonsense\r\n", False),
        (b"GET HTTP/1.1\r\n", False),
        (b"GET relative HTTP/1.1\r\n", False),
        (b" / HTTP/1.1\r\n", False),
        (b"GET  / HTTP/1.1\r\n", False),
        (b"GET / HTTP/2\r\n", False),
    ],
)
def test_request_line(web, line, valid):
    if valid:
        web.check_request_line(line)
    else:
        with pytest.raises(ValueError, match="invalid"):
            web.check_request_line(line)


@pytest.mark.parametrize(
    "line",
    [
        b"Host: board\r\n",
        b"X-Custom_Header: value\r\n",
        b"Content-Length: 0\r\n",
        b"Content-Length:  000 \r\n",
    ],
)
def test_accepts_headers_without_a_body(web, line):
    assert web.check_header_line(line, set()) == line.split(b":")[0].lower()


@pytest.mark.parametrize(
    ("line", "seen", "message"),
    [
        (b"Host: board\n", set(), "invalid header line"),
        (b"Host board\r\n", set(), "invalid or duplicate"),
        (b": board\r\n", set(), "invalid or duplicate"),
        (b" Host: board\r\n", set(), "invalid or duplicate"),
        (b"Host : board\r\n", set(), "invalid or duplicate"),
        (b"host: again\r\n", {b"host"}, "invalid or duplicate"),
        (b"HOST: again\r\n", {b"host"}, "invalid or duplicate"),
        (b"Content-Length: 1\r\n", set(), "bodies are unsupported"),
        (b"Content-Length: -1\r\n", set(), "bodies are unsupported"),
        (b"Content-Length:\r\n", set(), "bodies are unsupported"),
        (b"Transfer-Encoding: chunked\r\n", set(), "bodies are unsupported"),
    ],
)
def test_rejects_malformed_repeated_or_body_headers(web, line, seen, message):
    with pytest.raises(ValueError, match=message):
        web.check_header_line(line, seen)


def test_accepts_a_valid_upgrade(web):
    assert web.valid_upgrade(_UPGRADE) is True


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("Upgrade", "h2c"),
        ("Connection", "notupgrade"),
        ("Sec-WebSocket-Version", "12"),
        ("Sec-WebSocket-Key", "invalid"),
        ("Sec-WebSocket-Key", "!" * 24),
        ("Sec-WebSocket-Key", "YQ" + "=" * 22),
        ("Sec-WebSocket-Key", _KEY[:-2] + "Q="),
        ("Sec-WebSocket-Key", None),
    ],
)
def test_rejects_invalid_upgrades(web, name, value):
    headers = {**_UPGRADE, name: value}
    if value is None:
        del headers[name]
    assert web.valid_upgrade(headers) is False


@pytest.mark.parametrize("opcode", [0x88, 0x89, 0x8A])
@pytest.mark.parametrize("length", [0, 125])
def test_accepts_masked_final_control_frames(web, opcode, length):
    web.check_control_header(bytes((opcode, 0x80 | length)))


@pytest.mark.parametrize(
    "header",
    [
        b"\x81\x80",  # text
        b"\x82\xfd",  # binary
        b"\x80\x80",  # continuation
        b"\x09\x80",  # fragmented ping
        b"\xc9\x80",  # reserved bit
        b"\x8b\x80",  # reserved opcode
        b"\x89\x00",  # unmasked
        b"\x89\xfe",  # 16-bit length
        b"\x89\xff",  # 64-bit length
    ],
)
def test_rejects_data_fragmented_unmasked_or_long_frames(web, header):
    with pytest.raises(ValueError, match="unsupported WebSocket frame"):
        web.check_control_header(header)


@pytest.mark.parametrize(
    "payload", [b"", b"\x03\xe8", b"\x03\xe8bye", b"\x0b\xb8", b"\x13\x87", b"\x03\xf3\xc3\xa9"]
)
def test_accepts_close_payloads(web, payload):
    web.check_close_payload(payload)


@pytest.mark.parametrize(
    "payload",
    [
        b"\x03",  # half a code
        b"\x00\x01",  # unassigned code
        b"\x03\xed",  # 1005 is reserved for "no status"
        b"\x13\x88",  # 5000 is outside the private range
        b"\x03\xe8\xff",  # invalid UTF-8 reason
    ],
)
def test_rejects_close_payloads(web, payload):
    with pytest.raises(ValueError):
        web.check_close_payload(payload)


@pytest.mark.parametrize(
    ("tokens", "elapsed_ms", "expected_tokens", "expected_anchor"),
    [
        (0, 249, 0, 0),
        (0, 250, 1, 250),
        (0, 749, 2, 500),
        (3, 10_000, 4, 10_000),
    ],
)
def test_token_bucket_refills_whole_periods_up_to_the_cap(
    web, tokens, elapsed_ms, expected_tokens, expected_anchor
):
    assert web.refill_tokens(tokens, 0, elapsed_ms, 250) == (expected_tokens, expected_anchor)


def test_token_bucket_refills_across_tick_wrap(web, firmware_module):
    period = firmware_module.time._PERIOD

    assert web.refill_tokens(0, period - 100, 400, 500) == (1, 400)


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
