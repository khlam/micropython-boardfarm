"""An asyncio HTTP server small enough to sit beside a firmware control loop."""

import asyncio

from micropython import const

from httpd.websocket import Broadcast, upgrade_response

# Every interface, because the address a board is reachable on is decided by
# whatever brought its network up, not by the application.
_BIND_ADDRESS = "0.0.0.0"  # noqa: S104 - a LAN appliance has no other useful bind
_BACKLOG = const(2)

# A browser's request line and headers fit far inside both of these. Bounding
# them is what stops a broken or hostile peer from growing a heap this server
# shares with a sensor loop.
_MAX_HEADER_LINE = const(256)
_MAX_HEADERS = const(32)

_BAD_REQUEST = b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
_NOT_FOUND = b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
_NOT_ALLOWED = b"HTTP/1.1 405 Method Not Allowed\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
_UNAVAILABLE = b"HTTP/1.1 503 Service Unavailable\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"

_BODY_METHODS = ("GET", "HEAD")


class Server:
    """Serve fixed pages and WebSocket streams over one listening socket."""

    def __init__(self, port: int = 80) -> None:
        """Register routes against a port without binding it yet.

        Binding is deferred to :meth:`start` so a caller can build the whole
        server at import time and only open it once the network is up.

        Args:
            port: TCP port to listen on.
        """
        self._port = port
        self._pages = {}
        self._streams = {}
        self._listener = None

    def page(
        self,
        path: str,
        body: bytes,
        content_type: str = "text/html; charset=utf-8",
        encoding: str | None = None,
    ) -> None:
        """Serve one unchanging body at ``path``.

        The headers are built once here rather than per request, and the body is
        referenced rather than copied, so a page frozen into firmware is served
        straight out of ROM.

        Args:
            path: Request path, query string excluded.
            body: Response body exactly as it goes on the wire.
            content_type: Value for the ``Content-Type`` header.
            encoding: Value for ``Content-Encoding``, or None when ``body`` is
                already in its natural form. Pre-compressed bodies are the point:
                the encoder never runs on the chip.
        """
        self._pages[path] = (_page_headers(len(body), content_type, encoding), body)

    def stream(self, path: str, greeting: str | None = None) -> Broadcast:
        """Accept WebSocket clients at ``path`` and return their fan-out.

        Args:
            path: Request path clients connect to.
            greeting: Optional line sent to each client on connect.

        Returns:
            The :class:`~httpd.websocket.Broadcast` to push lines into.
        """
        broadcast = Broadcast(greeting=greeting)
        self._streams[path] = broadcast
        return broadcast

    async def start(self) -> None:
        """Bind the port and begin accepting connections in the background."""
        # backlog stays a keyword: CPython accepts it no other way, and host
        # tests exercise this module through the MicroPython stubs.
        self._listener = await asyncio.start_server(
            self._handle, _BIND_ADDRESS, self._port, backlog=_BACKLOG
        )

    async def _handle(self, reader: object, writer: object) -> None:
        """Serve one connection to completion, then close it.

        Nothing a peer does escapes this frame. A client that vanishes mid-header
        or speaks nonsense is ordinary traffic on a LAN, and the loop that feeds
        this server must never see it.
        """
        try:
            request = await _read_request(reader)
            if request is None:
                await _write(writer, _BAD_REQUEST)
            else:
                await self._dispatch(reader, writer, *request)
        except (OSError, ValueError):
            pass
        finally:
            writer.close()
            try:  # noqa: SIM105 — contextlib not available on MicroPython
                await writer.wait_closed()
            except OSError:
                pass

    async def _dispatch(
        self, reader: object, writer: object, method: str, path: str, headers: dict
    ) -> None:
        """Route one parsed request to its stream or page."""
        broadcast = self._streams.get(path)
        if broadcast is not None:
            await _upgrade(reader, writer, broadcast, headers)
            return
        page = self._pages.get(path)
        if page is None:
            await _write(writer, _NOT_FOUND)
            return
        if method not in _BODY_METHODS:
            await _write(writer, _NOT_ALLOWED)
            return
        headers_bytes, body = page
        writer.write(headers_bytes)
        if method != "HEAD":
            writer.write(body)
        await writer.drain()


async def _upgrade(reader: object, writer: object, broadcast: Broadcast, headers: dict) -> None:
    """Complete a WebSocket handshake and hand the connection to its fan-out."""
    key = headers.get("sec-websocket-key")
    if key is None or "websocket" not in headers.get("upgrade", "").lower():
        await _write(writer, _BAD_REQUEST)
        return
    if broadcast.full():
        # Refuse rather than evict: the client already watching asked first, and
        # an unbounded client list is exactly what would exhaust the heap.
        await _write(writer, _UNAVAILABLE)
        return
    await _write(writer, upgrade_response(key))
    await broadcast.serve(reader, writer)


async def _read_request(reader: object) -> tuple | None:
    """Read the request line and headers.

    Args:
        reader: Stream reader positioned at the start of the request.

    Returns:
        ``(method, path, headers)`` with header names lowercased, or None when
        the request is malformed or exceeds the header bounds.
    """
    line = await reader.readline()
    if not line or len(line) > _MAX_HEADER_LINE:
        return None
    fields = line.decode().split()
    if len(fields) < 2:
        return None
    method = fields[0]
    path = fields[1].split("?", 1)[0]
    headers = {}
    for _ in range(_MAX_HEADERS):
        line = await reader.readline()
        if not line or line in (b"\r\n", b"\n"):
            return method, path, headers
        if len(line) > _MAX_HEADER_LINE:
            return None
        name, _separator, value = line.decode().partition(":")
        headers[name.strip().lower()] = value.strip()
    return None


async def _write(writer: object, payload: bytes) -> None:
    """Write one complete response and wait for it to leave."""
    writer.write(payload)
    await writer.drain()


def _page_headers(length: int, content_type: str, encoding: str | None) -> bytes:
    """Build the response headers a registered page is served with."""
    lines = [
        "HTTP/1.1 200 OK",
        "Content-Type: " + content_type,
        "Content-Length: " + str(length),
        # The page ships inside the firmware, so a cached copy can outlive the
        # build that produced it and disagree with the stream it renders.
        "Cache-Control: no-cache",
        "Connection: close",
    ]
    if encoding is not None:
        lines.insert(2, "Content-Encoding: " + encoding)
    return ("\r\n".join(lines) + "\r\n\r\n").encode()
