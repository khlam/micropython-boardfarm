"""Shared stream fakes and fixtures for the httpd host tests."""

import asyncio

import pytest

from httpd import Server
from micropython_stubs import asyncio_extras


@pytest.fixture(autouse=True)
def _micropython_asyncio(monkeypatch):
    """Install the MicroPython-only asyncio names onto the real asyncio module."""
    asyncio_extras.install(monkeypatch)


@pytest.fixture
def server():
    """A Server with no routes registered yet."""
    return Server(port=8080)


@pytest.fixture
def reader():
    """Return a builder for a stream reader over a fixed script of bytes."""
    return _Reader


@pytest.fixture
def writer():
    """Return a builder for a stream writer that accumulates what it is sent."""
    return _Writer


@pytest.fixture
def serve(reader, writer):
    """Return a callable running one request through a server's connection handler."""

    def _serve(server: Server, request_bytes: bytes) -> bytes:
        """Return everything the server wrote back for one request.

        Args:
            server: The Server under test, with its routes already registered.
            request_bytes: The complete request exactly as a peer would send it.

        Returns:
            The bytes the server wrote to the connection.
        """
        sink = writer()
        asyncio.run(server._handle(reader(request_bytes), sink))
        return bytes(sink.buffer)

    return _serve


@pytest.fixture
def listener(monkeypatch):
    """Replace asyncio.start_server so start() binds a recorded fake listener."""
    created = []

    async def _start_server(_handler, address, port, backlog=None):
        """Record one bind and hand back a listener the test can inspect."""
        fake = _Listener(address, port, backlog)
        created.append(fake)
        return fake

    monkeypatch.setattr(asyncio, "start_server", _start_server)
    return created


class _Reader:
    """A stream reader over a fixed script of bytes.

    Reads past the end raise ``EOFError``, which is how MicroPython's
    ``readexactly`` reports a peer that hung up mid-frame.
    """

    def __init__(self, payload: bytes = b"") -> None:
        """Position the reader at the start of ``payload``."""
        self._payload = payload
        self._at = 0

    @property
    def bytes_read(self) -> int:
        """Return how many bytes the server consumed."""
        return self._at

    async def readexactly(self, count: int) -> bytes:
        """Return exactly ``count`` bytes, raising EOFError when short.

        Args:
            count: Number of bytes the caller requires.

        Returns:
            The requested bytes.

        Raises:
            EOFError: Fewer than ``count`` bytes remain.
        """
        end = self._at + count
        if end > len(self._payload):
            self._at = len(self._payload)
            raise EOFError("stream exhausted")
        chunk = self._payload[self._at : end]
        self._at = end
        return chunk


class _Writer:
    """A stream writer that accumulates everything written to it."""

    def __init__(self, *, fail_on_write: bool = False, fail_on_wait_closed: bool = False) -> None:
        """Start with an empty buffer and an open connection."""
        self.buffer = bytearray()
        self.closed = False
        self.waited = False
        self._fail_on_write = fail_on_write
        self._fail_on_wait_closed = fail_on_wait_closed

    def write(self, payload: bytes) -> None:
        """Append one payload, or raise when the fake is scripted to fail.

        Args:
            payload: Bytes the server is sending.

        Raises:
            OSError: The fake was built to model a dropped connection.
        """
        if self._fail_on_write:
            raise OSError("connection reset")
        self.buffer += payload

    async def drain(self) -> None:
        """Accept the write; nothing is buffered outside this object."""

    def close(self) -> None:
        """Mark the connection closed."""
        self.closed = True

    async def wait_closed(self) -> None:
        """Record the wait, or raise when the fake is scripted to fail.

        Raises:
            OSError: The fake was built to model a socket already torn down.
        """
        self.waited = True
        if self._fail_on_wait_closed:
            raise OSError("already gone")


class _Listener:
    """The object asyncio.start_server hands back, recording its bind."""

    def __init__(self, address: str, port: int, backlog: int | None) -> None:
        """Record the arguments start() bound with."""
        self.address = address
        self.port = port
        self.backlog = backlog
