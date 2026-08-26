"""RFC 6455 server framing and the fan-out that keeps connected browsers fed."""

import asyncio
import binascii
import hashlib
from collections import deque

from micropython import const

# The literal RFC 6455 defines. Concatenating it with the client's key and
# hashing the pair is the whole proof that the handshake was understood.
_GUID = b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

_TEXT_FRAME = const(0x81)
_OPCODE_MASK = const(0x0F)
_OPCODE_CLOSE = const(0x08)
_MASKED = const(0x80)
_LENGTH_MASK = const(0x7F)

# Payloads shorter than this ride in the header's own length byte; up to
# _MAX_PAYLOAD a 16-bit length follows; beyond that the length is 64-bit.
_EXTENDED_LENGTH = const(126)
_HUGE_LENGTH = const(127)
_MAX_PAYLOAD = const(0xFFFF)
_MASK_SIZE = const(4)

# Frames a client may have waiting. Bounded because a browser that stops reading
# must cost a fixed amount of a heap shared with a sensor loop, and drop-oldest
# because on live telemetry the newest frame is the one worth keeping.
_OUTBOX_DEPTH = const(8)

# Connections one Broadcast will hold at once. Small on purpose: each costs two
# asyncio tasks and an outbox, and this is a diagnostics view, not a service.
_MAX_CLIENTS = const(3)

# Client payloads are read only to get them out of the socket, so they are
# discarded a bounded chunk at a time rather than allocated whole.
_DISCARD_CHUNK = const(64)


class Broadcast:
    """Fan one stream of text out to every client connected to a path."""

    def __init__(self, greeting: str | None = None) -> None:
        """Create an empty fan-out.

        Args:
            greeting: Optional line sent to each client the moment it connects,
                before any broadcast reaches it. A client that joins mid-stream
                has missed everything before it, so this is where a protocol puts
                whatever state a late arrival needs to make sense of the rest.
        """
        self._greeting = greeting
        self._clients = []

    def send(self, text: str) -> None:
        """Queue one line for every connected client.

        Frames the payload once and shares that one bytes object across every
        outbox, because the caller is a hot loop and the clients all receive the
        same thing.

        This neither raises nor blocks: it is called from producers that must not
        be disturbed by the state of a browser tab, including the MicroPython
        scheduler. A client that cannot keep up loses frames rather than slowing
        the producer down.

        Args:
            text: One complete message. Silently dropped if it cannot be framed.
        """
        if not self._clients:
            return
        try:
            payload = frame(text)
        except ValueError:
            return
        for client in self._clients:
            client.enqueue(payload)

    def full(self) -> bool:
        """Return whether another client would exceed the connection ceiling."""
        return len(self._clients) >= _MAX_CLIENTS

    async def serve(self, reader: object, writer: object) -> None:
        """Run one client that has completed its handshake, until it goes away.

        Args:
            reader: Stream reader for the upgraded connection.
            writer: Stream writer for the upgraded connection.
        """
        client = _Client(reader, writer)
        self._clients.append(client)
        incoming = asyncio.create_task(client.discard_input())
        try:
            if self._greeting is not None:
                client.enqueue(frame(self._greeting))
            await client.drain_outbox()
        finally:
            incoming.cancel()
            self._clients.remove(client)


def upgrade_response(key: str) -> bytes:
    """Return the 101 response that completes the opening handshake.

    Args:
        key: The client's ``Sec-WebSocket-Key`` header value.

    Returns:
        The complete response, headers and terminator included.
    """
    digest = hashlib.sha1(key.encode() + _GUID).digest()  # noqa: S324 - RFC 6455 fixes SHA-1 here
    accept = binascii.b2a_base64(digest).strip()
    return (
        b"HTTP/1.1 101 Switching Protocols\r\n"
        b"Upgrade: websocket\r\n"
        b"Connection: Upgrade\r\n"
        b"Sec-WebSocket-Accept: " + accept + b"\r\n\r\n"
    )


def frame(text: str) -> bytes:
    """Encode one complete text frame.

    Server frames are never masked, and every line this carries is a single
    unfragmented message, so the two variable-length forms below are the whole
    encoder.

    Args:
        text: The message payload.

    Returns:
        Header and payload as one bytes object, ready to write.

    Raises:
        ValueError: The encoded payload needs a 64-bit length.
    """
    payload = text.encode()
    length = len(payload)
    if length < _EXTENDED_LENGTH:
        return bytes((_TEXT_FRAME, length)) + payload
    if length > _MAX_PAYLOAD:
        raise ValueError("payload is too long for one frame")
    return bytes((_TEXT_FRAME, _EXTENDED_LENGTH, length >> 8, length & 0xFF)) + payload


class _Client:
    """One connected peer, its pending frames, and the two tasks that run it."""

    def __init__(self, reader: object, writer: object) -> None:
        """Wrap an upgraded connection with an empty outbox."""
        self._reader = reader
        self._writer = writer
        # MicroPython's deque takes its bound positionally and requires the
        # iterable, so the keyword form ruff prefers would not run on the chip.
        self._outbox = deque((), _OUTBOX_DEPTH)  # noqa: RUF037
        self._ready = asyncio.ThreadSafeFlag()
        self.closed = False

    def enqueue(self, payload: bytes) -> None:
        """Queue one pre-framed payload and wake the writer, doing no I/O.

        Appending and flagging are both safe from the MicroPython scheduler,
        which is what lets a producer running there feed a client at all.
        """
        self._outbox.append(payload)
        self._ready.set()

    def close(self) -> None:
        """Mark the client gone and wake the writer so it can retire."""
        self.closed = True
        self._ready.set()

    async def drain_outbox(self) -> None:
        """Write queued frames until the connection ends."""
        while not self.closed:
            await self._ready.wait()
            try:
                while self._outbox:
                    self._writer.write(self._outbox.popleft())
                    await self._writer.drain()
            except OSError:
                self.close()

    async def discard_input(self) -> None:
        """Consume whatever the client sends, honouring only its close frame.

        This direction carries nothing the firmware wants, but it still has to be
        read: unread bytes fill the socket buffer, and a close frame is how a
        browser says a tab went away.
        """
        try:
            while not self.closed and await self._read_frame():
                pass
        except (OSError, EOFError):
            pass
        self.close()

    async def _read_frame(self) -> bool:
        """Discard one client frame, returning False when it was a close."""
        header = await self._reader.readexactly(2)
        length = header[1] & _LENGTH_MASK
        if length == _EXTENDED_LENGTH:
            extended = await self._reader.readexactly(2)
            length = (extended[0] << 8) | extended[1]
        elif length == _HUGE_LENGTH:
            # A 64-bit length means megabytes this endpoint never asked for, and
            # skipping them still means reading them. Hang up instead.
            return False
        if header[1] & _MASKED:
            await self._reader.readexactly(_MASK_SIZE)
        while length > 0:
            length -= len(await self._reader.readexactly(min(length, _DISCARD_CHUNK)))
        return header[0] & _OPCODE_MASK != _OPCODE_CLOSE
