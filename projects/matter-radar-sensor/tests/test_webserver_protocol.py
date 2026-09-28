"""HTTP and WebSocket input limits, admission rates, and failure classes."""

import errno
from collections.abc import Callable
from contextlib import AbstractContextManager
from contextlib import nullcontext as returns
from types import ModuleType

import pytest

_KEY = "dGhlIHNhbXBsZSBub25jZQ=="
_UPGRADE = {
    "Upgrade": "websocket",
    "Connection": "keep-alive, Upgrade",
    "Sec-WebSocket-Key": _KEY,
    "Sec-WebSocket-Version": "13",
}


def _rejects(message: str) -> AbstractContextManager:
    """Expect the ValueError a malformed input raises, naming its rule.

    Args:
        message: Pattern the error message must match.

    Returns:
        A context that fails unless its body raises that ValueError.
    """
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
def test_request_line(web: ModuleType, line: bytes, outcome: AbstractContextManager):
    """Only a CRLF-terminated ``METHOD /path HTTP/1.x`` request line is accepted.

    Args:
        web: The firmware webserver module.
        line: The raw request line.
        outcome: Passes, or expects the ValueError naming the broken rule.
    """
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
def test_header_line(
    web: ModuleType, line: bytes, seen: set[bytes], outcome: AbstractContextManager
):
    """A well-formed, first-seen header returns its lowercased name; bodies are refused.

    Args:
        web: The firmware webserver module.
        line: The raw header line.
        seen: Lowercased header names already received.
        outcome: Yields the expected name, or expects the ValueError naming the
            broken rule.
    """
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
def test_valid_upgrade(web: ModuleType, changes: dict[str, str | None], valid: bool):
    """Only a complete RFC 6455 upgrade with a 16-byte base64 key is valid.

    Args:
        web: The firmware webserver module.
        changes: Edits to a valid upgrade's headers; a None value removes that header.
        valid: Whether the edited headers form a valid upgrade.
    """
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
def test_control_header(web: ModuleType, header: bytes, outcome: AbstractContextManager):
    """Only final, masked close/ping/pong frames of at most 125 bytes are accepted.

    Args:
        web: The firmware webserver module.
        header: The frame's first two bytes.
        outcome: Passes, or expects the ValueError for an unsupported frame.
    """
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
def test_close_payload(web: ModuleType, payload: bytes, outcome: AbstractContextManager):
    """A close payload is empty, or a sendable close code and a UTF-8 reason.

    Args:
        web: The firmware webserver module.
        payload: The unmasked close frame payload.
        outcome: Passes, or expects the ValueError naming the broken rule.
    """
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
    web: ModuleType,
    firmware_module: Callable[[str], ModuleType],
    tokens: int,
    token_ms: int,
    now_ms: int,
    period_ms: int,
    expected: tuple[int, int],
):
    """Each whole elapsed period adds a token up to the cap, advancing the anchor.

    Args:
        web: The firmware webserver module.
        firmware_module: Supplies the fake clock's wrap period.
        tokens: Tokens held before the refill.
        token_ms: When the bucket last refilled.
        now_ms: The current tick.
        period_ms: Milliseconds per token.
        expected: The tokens and anchor after the refill.
    """
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
def test_only_memory_and_descriptor_exhaustion_are_resource_failures(
    web: ModuleType, exception: Exception, reason: str | None
):
    """Heap, buffer, and descriptor exhaustion are resource failures; nothing else is.

    Args:
        web: The firmware webserver module.
        exception: The failure to classify.
        reason: The cooldown reason it maps to, or None when it isn't a resource failure.
    """
    assert web.resource_failure(exception) == reason


@pytest.fixture
def web(firmware_module: Callable[[str], ModuleType]) -> ModuleType:
    """The firmware webserver module, imported fresh.

    Args:
        firmware_module: Imports the module from the firmware directory.

    Returns:
        The webserver module.
    """
    return firmware_module("webserver")
