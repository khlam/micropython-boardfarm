"""Serve dashboard HTTP and WebSocket traffic within bounded MCU resources.

WebServer owns routes, report buffering, address announcements, and startup.
Private helpers own sockets, connection cleanup, and recovery. Protocol limits
are pure functions at the end of the module, so they can be checked alone.
"""

import asyncio
import binascii
import errno
import gc
import socket
import time

import dashboard_page
import ujson
from microdot import Microdot, Request, Response, microdot
from microdot.websocket import WebSocket, WebSocketError
from micropython import const

from matter.emit import emit, error

# MicroPython does not provide the host's typing modules.
TYPE_CHECKING = False
if TYPE_CHECKING:
    from collections.abc import Callable

# Poll because Matter does not report address changes to this application.
_ADDRESS_POLL_MS = const(1_000)
# Let Matter finish its high-current startup before starting more network work.
_DASHBOARD_BOOT_DELAY_MS = const(15_000)
_DASHBOARD_RETRY_MS = const(5_000)


_MAX_PAYLOAD = const(1024)
# Each token bucket admits a burst of this many before refilling one per period.
_TOKENS = const(4)
_ADMISSION_PERIOD_MS = const(500)
_CONTROL_PERIOD_MS = const(250)
_MAX_CONNECTION_MS = const(10 * 60 * 1000)
_MIN_HEAP = const(64 * 1024)
_RESUME_HEAP = const(96 * 1024)
_RESOURCE_ERRORS = (errno.ENOMEM, errno.ENOBUFS, 23, 24)
# Peer and resource failures end one connection; handle_error also suspends on
# resource failures.
_EXPECTED_ERRORS = (
    MemoryError,
    OSError,
    EOFError,
    ValueError,
    WebSocketError,
    asyncio.TimeoutError,
)
_CLOSE_CODES = (1000, 1001, 1002, 1003, 1007, 1008, 1009, 1010, 1011, 1012, 1013, 1014)
_LF = b"\n"
_CRLF = b"\r\n"
_HEADER_NAME_BYTES = b"!#$%&'*+-.^_`|~0123456789abcdefghijklmnopqrstuvwxyz"
_TRANSFER_ENCODING = b"transfer-encoding"
_CONTENT_LENGTH = b"content-length"


class WebServer:
    """Own dashboard routes, telemetry buffering, and network supervision."""

    def __init__(self, port_name: str) -> None:
        """Define routes without opening sockets.

        Args:
            port_name: Sensor port label sent when a viewer connects.
        """
        self._port_name = port_name
        self._address = None
        self._failed = False
        self._reported_state = (None, None)
        self._task = None
        self._viewer = None
        self._viewer_lock = asyncio.Lock()
        self._pending = [None, None]
        self._app = Microdot()
        self._server = _SocketServer(self._app)
        # Microdot's default exception printer writes plain text to MCU stdout.
        microdot.print_exception = self._report_error
        self._app.get("/")(self._page)
        self._app.get("/ws")(self._stream)
        self._app.errorhandler(MemoryError)(self._resource_error)
        self._app.errorhandler(OSError)(self._resource_error)

    async def run(self, network_address: "Callable[[], str | None]") -> None:
        """Keep the dashboard available after Matter has a network address.

        The server listens on every interface, so an address change only needs
        a new dashboard address report. It reports each failure period once and
        keeps retrying; dashboard failures do not change occupancy.

        Args:
            network_address: Callable returning Matter's current address or None.
        """
        await asyncio.sleep_ms(_DASHBOARD_BOOT_DELAY_MS)
        while True:
            try:
                delay_ms = self._update_address(network_address)
            except MemoryError as exception:
                self._server.handle_error(exception)
                delay_ms = _DASHBOARD_RETRY_MS
            await asyncio.sleep_ms(delay_ms)

    def queue_report(self, line: str) -> None:
        """Retain at most two reports without blocking the sensor or Matter tasks."""
        if not self._viewer or self._server.state != "running" or len(line) > _MAX_PAYLOAD:
            return
        if self._pending[0] is None:
            self._pending[0] = line
        elif self._pending[1] is None:
            self._pending[1] = line
        else:
            self._pending[0] = self._pending[1]
            self._pending[1] = line

    def _update_address(self, network_address: "Callable[[], str | None]") -> int:
        """Check the dashboard once and return the delay before the next check.

        An address failure keeps the last reported address and is written out
        only once per failure period.

        Args:
            network_address: Callable returning Matter's current address or None.

        Returns:
            Milliseconds to wait before checking again.
        """
        try:
            self._report_state()
            address = network_address()
        except OSError as exception:
            if not self._failed:
                error("dashboard", str(exception))
            self._failed = True
            return _DASHBOARD_RETRY_MS
        if address is not None:
            if self._task is None:
                self._task = _start_task(self._server.run())
            if self._server.state != "running":
                return _ADDRESS_POLL_MS
            if address != self._address:
                emit({"event": "dashboard", "state": "ready", "url": "http://" + address + "/"})
        self._address = address
        self._failed = False
        return _ADDRESS_POLL_MS

    def _report_state(self) -> None:
        """Report each lifecycle transition once, after resource cleanup."""
        state, reason = self._server.state, self._server.reason
        if (state, reason) == self._reported_state:
            return
        report = {"diag": "web", "state": state}
        if reason is not None:
            report["reason"] = reason
        emit(report)
        self._reported_state = (state, reason)
        if state != "running":
            self._address = None

    async def _page(self, _request: object) -> Response:
        """Serve the frozen dashboard without decompressing it on the board."""
        return Response(
            dashboard_page.PAGE,
            headers={
                "Content-Type": "text/html; charset=utf-8",
                "Content-Encoding": dashboard_page.ENCODING,
                "Cache-Control": "no-cache",
            },
        )

    async def _stream(self, request: object) -> Response:
        """Stream reports to one viewer and release both tasks on disconnect."""
        # Reject invalid upgrades before they can claim the viewer slot.
        if not valid_upgrade(request.headers):
            self._app.abort(400)
        websocket = _WebSocket(request)
        if not await self._claim_viewer(websocket):
            return Response("Dashboard already open", 503)
        sender = None
        try:
            await websocket.handshake()
            await websocket.send(ujson.dumps({"event": "connected", "port": self._port_name}))
            sender = _start_task(self._send_reports(websocket))
            await websocket.controls()
        except _EXPECTED_ERRORS as exception:
            self._server.handle_error(exception)
        finally:
            try:
                if sender is not None:
                    sender.cancel()
                    try:  # noqa: SIM105 - contextlib is unavailable on MicroPython.
                        await sender
                    except asyncio.CancelledError:
                        pass
            finally:
                self._viewer = None
                self._pending[0] = self._pending[1] = None
        return Response.already_handled

    async def _claim_viewer(self, websocket: object) -> bool:
        """Join a displaced viewer before giving its slot to a takeover request."""
        async with self._viewer_lock:
            if self._viewer is not None:
                if websocket.request.args.get("takeover") != "1":
                    return False
                peer = self._viewer.request.sock[0]
                peer.close()
                if peer.task is not None:
                    await peer.task
            self._viewer = websocket
            return True

    async def _send_reports(self, websocket: object) -> None:
        """Send queued telemetry outside the synchronous JSON producer."""
        try:
            while True:
                line = self._pending[0]
                if line is not None:
                    self._pending[0] = self._pending[1]
                    self._pending[1] = None
                    if len(line.encode()) <= _MAX_PAYLOAD:
                        await websocket.send(line)
                await asyncio.sleep_ms(10)
        except _EXPECTED_ERRORS as exception:
            self._server.handle_error(exception)
        finally:
            # Wake the control reader when a write fails or its task is cancelled.
            websocket.request.sock[0].close()

    def _report_error(self, exception: Exception) -> None:
        """Keep Microdot request errors within the serial JSON protocol."""
        if not self._server.handle_error(exception):
            error("dashboard", str(exception))

    async def _resource_error(self, _request: object, exception: Exception) -> Response:
        """Avoid allocating an error response after a resource failure."""
        self._server.handle_error(exception)
        return Response.already_handled


class _SocketServer:
    """Own admission, connection tasks, and recovery for a Microdot application."""

    def __init__(self, app: object) -> None:
        """Retain the application without opening sockets."""
        self._app = app
        self._listener = None
        self._connections = []
        self.state = "stopped"
        self.reason = None
        self._retry_ms = 5000
        self._failed = False
        self._suspended_ms = 0
        self._healthy_ms = 0
        self._heap_ms = 0
        self._token_ms = 0
        self._tokens = _TOKENS

    async def run(self) -> None:
        """Supervise sockets, joining every handler before reusing its slot."""
        try:
            while True:
                try:
                    await self._reap()
                    self._step(time.ticks_ms())
                except MemoryError:
                    self._suspend("memory")
                except OSError:
                    self._suspend("socket")
                await asyncio.sleep_ms(10)
        finally:
            self._close()
            while self._connections:
                await self._join(self._connections[0])
            self.state = "stopped"

    def handle_error(self, exception: Exception) -> bool:
        """Handle resource failures even when Microdot catches the exception.

        Args:
            exception: Failure from a parser, route, or socket operation.

        Returns:
            Whether this is an expected peer or resource failure.
        """
        reason = resource_failure(exception)
        if reason is not None:
            self._suspend(reason)
        return isinstance(exception, _EXPECTED_ERRORS)

    async def _reap(self) -> None:
        """Retrieve task results before freeing connection slots."""
        index = 0
        while index < len(self._connections):
            peer = self._connections[index]
            if peer.finished:
                await self._join(peer)
            else:
                index += 1

    async def _join(self, peer: object) -> None:
        """Join even a task cancelled before its first scheduled turn."""
        try:
            if peer.task is not None:
                await peer.task
        except asyncio.CancelledError:
            pass
        finally:
            peer.close()
            self._connections.remove(peer)

    def _step(self, now_ms: int) -> None:
        """Check recovery and memory before accepting at most one socket."""
        if self.state != "running":
            if self._connections or (
                self.state == "cooldown"
                and time.ticks_diff(now_ms, self._suspended_ms) < self._retry_ms
            ):
                return
            self.state = "stopped"
            self._resume(now_ms)
            return
        if time.ticks_diff(now_ms, self._heap_ms) >= 100:
            self._heap_ms = now_ms
            if gc.mem_free() < _MIN_HEAP:
                self._suspend("heap")
                return
        if time.ticks_diff(now_ms, self._healthy_ms) >= 60000:
            self._retry_ms = 5000
            self._failed = False
            self._healthy_ms = now_ms
        self._tokens, self._token_ms = refill_tokens(
            self._tokens, self._token_ms, now_ms, _ADMISSION_PERIOD_MS
        )
        self._accept()

    def _accept(self) -> None:
        """Admit one socket within capacity, closing it if handler setup fails."""
        try:
            sock, address = self._listener.accept()
        except OSError as exception:
            if exception.args[0] == errno.EAGAIN:
                return
            raise
        if len(self._connections) >= 2 or not self._tokens:
            sock.close()
            return
        self._tokens -= 1
        peer = None
        try:
            sock.setblocking(False)
            peer = _Connection(sock)
            self._connections.append(peer)
            peer.task = _start_task(self._serve(peer, address))
        except (OSError, MemoryError):
            if peer is not None:
                if peer in self._connections:
                    self._connections.remove(peer)
                peer.close()
            else:
                sock.close()
            raise

    async def _serve(self, peer: object, address: tuple) -> None:
        """Use Microdot parsing and routing within the owned socket lifetime."""
        try:
            try:
                request = await Request.create(self._app, peer, peer, address)
            except ValueError:
                request = None
            peer.check_read_deadline()
            peer.response_ms = time.ticks_ms()
            response = await self._app.dispatch_request(request)
            if peer.socket is not None and response is not Response.already_handled:
                response.headers["Connection"] = "close"
                await response.write(peer)
        except _EXPECTED_ERRORS as exception:
            self.handle_error(exception)
        finally:
            peer.close()
            peer.finished = True

    def _resume(self, now_ms: int) -> None:
        """Bind only after cleanup, backoff, and sufficient free heap."""
        gc.collect()
        if gc.mem_free() < _RESUME_HEAP:
            self._suspend("heap")
            return
        self._listener = socket.socket()
        self._listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listener.setblocking(False)
        self._listener.bind(socket.getaddrinfo("0.0.0.0", 80, 0, socket.SOCK_STREAM)[0][-1])  # noqa: S104 - board-local dashboard.
        self._listener.listen(2)
        self._tokens = _TOKENS
        self._token_ms = self._heap_ms = self._healthy_ms = now_ms
        self.state = "running"
        self.reason = None

    def _suspend(self, reason: str) -> None:
        """Release optional work before any diagnostic allocation."""
        if self.state == "cooldown":
            return
        if self._failed:
            self._retry_ms = min(60000, self._retry_ms * 2)
        self._failed = True
        self.state = "cooldown"
        self.reason = reason
        self._suspended_ms = time.ticks_ms()
        self._close()

    def _close(self) -> None:
        """Close all sockets and cancel other tasks without cancelling the caller."""
        listener = self._listener
        self._listener = None
        if listener is not None:
            try:  # noqa: SIM105 - contextlib is unavailable on MicroPython.
                listener.close()
            except (OSError, MemoryError):
                pass
        current = asyncio.current_task()
        for peer in self._connections:
            peer.close()
            if peer.task is not None and peer.task is not current:
                peer.task.cancel()
                peer.finished = True


class _Connection:
    """Present bounded asynchronous reads and writes over a nonblocking socket."""

    def __init__(self, sock: object) -> None:
        """Record request deadlines without reading or buffering input."""
        self.socket = sock
        self.task = None
        self.finished = False
        self.started_ms = time.ticks_ms()
        self.response_ms = None
        self.write_started_ms = None
        self.frame_ms = None
        self.websocket = False
        self.total = 0
        self.lines = 0
        self.names = set()
        self.tokens = _TOKENS
        self.token_ms = self.started_ms
        self.lock = asyncio.Lock()

    async def readline(self) -> bytes:
        """Bound every line and reject body framing before Microdot sees it."""
        line = bytearray()
        while len(line) < 256 and self.total < 2048:
            byte = await self._receive(1)
            line.extend(byte)
            self.total += 1
            if byte == _LF:
                result = bytes(line)
                self._check_line(result)
                await asyncio.sleep_ms(10)
                return result
        raise ValueError("request exceeds bounds")

    def _check_line(self, line: bytes) -> None:
        """Check the request line, then each header, within the header count."""
        self.lines += 1
        if self.lines == 1:
            check_request_line(line)
        elif line != _CRLF:
            if self.lines > 33:
                raise ValueError("too many headers")
            self.names.add(check_header_line(line, self.names))

    async def read(self, count: int) -> bytes:
        """Validate control framing before Microdot reads any mask or payload."""
        if not self.websocket or count != 2:
            raise ValueError("unsupported read")
        self.frame_ms = None
        first = await self._receive(1)
        self.frame_ms = time.ticks_ms()
        header = first + await self._receive(1)
        check_control_header(header)
        self.tokens, self.token_ms = refill_tokens(
            self.tokens, self.token_ms, time.ticks_ms(), _CONTROL_PERIOD_MS
        )
        if not self.tokens:
            raise ValueError("control frame rate exceeded")
        self.tokens -= 1
        return header

    async def readexactly(self, count: int) -> bytes:
        """Read only the bounded mask or payload of an accepted control frame."""
        if not self.websocket or not 0 <= count <= 125:
            raise ValueError("unsupported payload read")
        result = bytearray()
        while len(result) < count:
            result.extend(await self._receive(count - len(result)))
        return bytes(result)

    async def _receive(self, count: int) -> bytes:
        """Use absolute connection, request, and partial-frame deadlines."""
        while True:
            self.check_read_deadline()
            if self.socket is None:
                raise EOFError
            try:
                data = self.socket.recv(count)
            except OSError as exception:
                if exception.args[0] != errno.EAGAIN:
                    raise
            else:
                if not data:
                    raise EOFError
                return data
            await asyncio.sleep_ms(10)

    def check_read_deadline(self) -> None:
        """Check wrap-safe connection, request, and partial-frame deadlines."""
        now_ms = time.ticks_ms()
        if time.ticks_diff(now_ms, self.started_ms) >= _MAX_CONNECTION_MS:
            raise asyncio.TimeoutError  # noqa: UP041 - MCU class.
        started = self.frame_ms if self.websocket else self.started_ms
        limit = 1000 if self.websocket else 2000
        if started is not None and time.ticks_diff(now_ms, started) >= limit:
            raise asyncio.TimeoutError  # noqa: UP041 - MCU class.

    async def awrite(self, data: bytes) -> None:
        """Send bounded slices with stalled-write and absolute response limits."""
        view = memoryview(data)
        offset = 0
        progress_ms = time.ticks_ms()
        while offset < len(view):
            now_ms = time.ticks_ms()
            if (
                time.ticks_diff(now_ms, progress_ms) >= 1000
                or (
                    self.response_ms is not None
                    and time.ticks_diff(now_ms, self.response_ms) >= 5000
                )
                or (
                    self.write_started_ms is not None
                    and time.ticks_diff(now_ms, self.write_started_ms) >= 1000
                )
            ):
                raise asyncio.TimeoutError  # noqa: UP041 - MCU class.
            if self.socket is None:
                raise EOFError
            try:
                count = self.socket.send(view[offset : offset + 512])
            except OSError as exception:
                if exception.args[0] != errno.EAGAIN:
                    raise
                count = 0
            if count:
                offset += count
                progress_ms = now_ms
            await asyncio.sleep_ms(10)

    def close(self) -> None:
        """Release the socket once, including during low-memory cleanup."""
        sock = self.socket
        self.socket = None
        if sock is not None:
            try:  # noqa: SIM105 - contextlib is unavailable on MicroPython.
                sock.close()
            except (OSError, MemoryError):
                pass


class _WebSocket(WebSocket):
    """Keep Microdot framing with guarded input and serialized, timed writes."""

    max_message_length = 125

    async def handshake(self) -> None:
        """Send the upgrade response before allowing WebSocket frame reads."""
        await super().handshake()
        peer = self.request.sock[0]
        peer.response_ms = None
        peer.websocket = True
        peer.names.clear()
        peer.token_ms = time.ticks_ms()

    async def send(self, data: str | bytes, opcode: int | None = None) -> None:
        """Bound a whole write, including waiting for another frame's lock."""
        peer = self.request.sock[1]
        started_ms = time.ticks_ms()
        # Poll a bounded lock wait without allocating timeout helper tasks.
        while peer.lock.locked():
            if time.ticks_diff(time.ticks_ms(), started_ms) >= 1000:
                raise asyncio.TimeoutError  # noqa: UP041 - MCU class.
            await asyncio.sleep_ms(10)
        async with peer.lock:
            peer.write_started_ms = started_ms
            try:
                await super().send(data, opcode)
            finally:
                peer.write_started_ms = None

    async def controls(self) -> None:
        """Process bounded controls and echo a valid close payload."""
        while True:
            opcode, payload = await self._read_frame()
            if opcode == self.CLOSE:
                check_close_payload(payload)
                await self.send(payload, self.CLOSE)
                return
            if opcode == self.PING:
                await self.send(payload, self.PONG)
            await asyncio.sleep_ms(10)


def _start_task(coroutine: object) -> asyncio.Task:
    """Release an unstarted coroutine if scheduling runs out of memory."""
    try:
        return asyncio.create_task(coroutine)
    except MemoryError:
        coroutine.close()
        raise


def resource_failure(exception: Exception) -> str | None:
    """Return the suspension reason for a resource failure, or None for anything else."""
    if isinstance(exception, MemoryError):
        return "memory"
    if isinstance(exception, OSError) and exception.args and exception.args[0] in _RESOURCE_ERRORS:
        return "socket"
    return None


def refill_tokens(tokens: int, token_ms: int, now_ms: int, period_ms: int) -> tuple:
    """Return a token bucket's count and anchor after whole periods have passed.

    Args:
        tokens: Tokens left in the bucket.
        token_ms: Tick the last whole refill period ended at.
        now_ms: Current tick.
        period_ms: Milliseconds to refill one token.

    Returns:
        The new ``(tokens, token_ms)`` pair, capped at the bucket size.
    """
    periods = time.ticks_diff(now_ms, token_ms) // period_ms
    if periods <= 0:
        return tokens, token_ms
    return min(_TOKENS, tokens + periods), time.ticks_add(token_ms, periods * period_ms)


def check_request_line(line: bytes) -> None:
    """Reject malformed start lines before Microdot splits their fields."""
    if not line.endswith(_CRLF):
        raise ValueError("invalid header line")
    parts = line[:-2].split(b" ")
    if (
        len(parts) != 3
        or not parts[0]
        or not parts[1].startswith(b"/")
        or parts[2] not in (b"HTTP/1.0", b"HTTP/1.1")
    ):
        raise ValueError("invalid request line")


def check_header_line(line: bytes, names: set) -> bytes:
    """Reject a malformed, repeated, or body-framing header and return its name.

    Args:
        line: One header line, including its CRLF.
        names: Lowercase header names already seen in this request.

    Returns:
        The lowercase header name.

    Raises:
        ValueError: The line is malformed, repeats a name, or frames a body.
    """
    if not line.endswith(_CRLF):
        raise ValueError("invalid header line")
    name, separator, value = line[:-2].partition(b":")
    name = name.lower()
    if (
        not separator
        or not name
        or any(byte not in _HEADER_NAME_BYTES for byte in name)
        or name in names
    ):
        raise ValueError("invalid or duplicate header")
    value = value.strip()
    if name == _TRANSFER_ENCODING or (name == _CONTENT_LENGTH and (not value or value.strip(b"0"))):
        raise ValueError("request bodies are unsupported")
    return name


def valid_upgrade(headers: dict) -> bool:
    """Return whether request headers form a valid WebSocket version 13 upgrade."""
    key = headers.get("Sec-WebSocket-Key", "")
    if (
        headers.get("Upgrade", "").lower() != "websocket"
        or "upgrade" not in headers.get("Connection", "").lower().replace(" ", "").split(",")
        or headers.get("Sec-WebSocket-Version") != "13"
        or len(key) != 24
    ):
        return False
    try:
        decoded = binascii.a2b_base64(key)
    except ValueError:
        return False
    return len(decoded) == 16 and binascii.b2a_base64(decoded).strip().decode() == key


def check_control_header(header: bytes) -> None:
    """Accept only final, masked close, ping, or pong frames of at most 125 bytes."""
    if header[0] not in (0x88, 0x89, 0x8A) or not 128 <= header[1] <= 253:
        raise ValueError("unsupported WebSocket frame")


def check_close_payload(payload: bytes) -> None:
    """Reject a close payload with a partial or unassigned code, or invalid UTF-8."""
    if len(payload) == 1:
        raise ValueError("invalid close payload")
    if len(payload) >= 2:
        code = (payload[0] << 8) | payload[1]
        if code not in _CLOSE_CODES and not 3000 <= code < 5000:
            raise ValueError("invalid close code")
        payload[2:].decode()
