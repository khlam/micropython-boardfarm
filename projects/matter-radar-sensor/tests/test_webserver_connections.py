"""Exercise real Microdot routes through bounded sockets and recovery."""

import asyncio
import errno
import time
from collections.abc import Callable
from types import SimpleNamespace

import pytest

from micropython_stubs.testing import json_lines

_GET = b"GET / HTTP/1.1\r\nHost: board\r\n\r\n"
_UPGRADE = (
    b"GET /ws HTTP/1.1\r\nHost: board\r\nUpgrade: websocket\r\n"
    b"Connection: Upgrade\r\nSec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
    b"Sec-WebSocket-Version: 13\r\n\r\n"
)
# Resource failures suspend the server; a peer reset ends only its connection.
_FAILURES = [
    (MemoryError(), "cooldown"),
    (OSError(errno.ENOBUFS), "cooldown"),
    (OSError(errno.ECONNRESET), "running"),
]


def _request_of(total: int) -> bytes:
    """Return a GET of ``total`` bytes whose every line stays within the line limit.

    Args:
        total: The request's length in bytes.

    Returns:
        The encoded request.
    """
    prefix = _GET[:-2] + b"".join(b"X-%d: " % i + b"a" * 230 + b"\r\n" for i in range(8))
    return prefix + b"Z: " + b"a" * (total - len(prefix) - 7) + b"\r\n\r\n"


@pytest.mark.parametrize(
    ("data", "status"),
    [
        (_GET, b"200"),
        (_request_of(2048), b"200"),
        (_request_of(2049), b"400"),
        (_GET.replace(b"/ ", b"/missing "), b"404"),
        (_GET.replace(b"GET", b"POST"), b"405"),
        (_GET[:-2] + b"X: " + b"a" * 251 + b"\r\n\r\n", b"200"),
        (_GET[:-2] + b"X: " + b"a" * 252 + b"\r\n\r\n", b"400"),
        (_GET[:-2] + b"".join(b"X-%d: a\r\n" % i for i in range(31)) + b"\r\n", b"200"),
        (_GET[:-2] + b"".join(b"X-%d: a\r\n" % i for i in range(32)) + b"\r\n", b"400"),
        (b"a" * 10000, b"400"),
        (b"GET / nonsense\r\n\r\n", b"400"),
        (_GET[:-2] + b"host: duplicate\r\n\r\n", b"400"),
        (_GET[:-2] + b"Content-Length: 999999999\r\n\r\nbody", b"400"),
        (_UPGRADE.replace(b"Version: 13", b"Version: 12"), b"400"),
        (b"", None),
    ],
)
def test_http_input_bounds(web: "Harness", data: bytes, status: bytes | None):
    """Each request gets one bounded response and closes, and none claims the viewer.

    Args:
        web: Drives the dashboard server.
        data: Everything the peer sends before closing.
        status: The response's status code, or None when the peer sends nothing.
    """

    async def run():
        sock = web.accept(data)
        if not data:
            sock.eof = True
        await web.pump()
        if status is not None:
            assert sock.outgoing.split(b" ")[1] == status
            assert b"Connection: close\r\n" in sock.outgoing
        assert not web.webserver._viewer
        assert sock.closed
        assert sock.consumed <= 2048
        assert max(sock.read_sizes) == 1
        if b"body" in data:
            assert sock.incoming.endswith(b"body")
        await web.close()

    asyncio.run(run())


def test_only_one_request_per_socket(web: "Harness"):
    """A second request pipelined on the same socket is left unread.

    Args:
        web: Drives the dashboard server.
    """

    async def run():
        sock = web.accept(_GET + _GET)
        await web.pump()
        assert sock.outgoing.count(b"200 OK") == 1
        assert sock.incoming == _GET
        await web.close()

    asyncio.run(run())


@pytest.mark.parametrize("header", [b"\x81\x80", b"\x89\xfe"])
def test_websocket_rejects_before_payload(web: "Harness", header: bytes):
    """An unsupported frame header closes the viewer before its payload is read.

    Args:
        web: Drives the dashboard server.
        header: A frame header the viewer must not accept.
    """

    async def run():
        sock = await web.upgrade()
        before = sock.consumed
        sock.incoming.extend(header + b"unread mask and payload")
        await web.pump()
        assert sock.closed
        assert sock.consumed - before == 2
        assert sock.incoming == b"unread mask and payload"
        assert not web.webserver._viewer
        await web.close()

    asyncio.run(run())


@pytest.mark.parametrize("payload", [b"", b"a" * 125])
def test_ping_echo_and_valid_close(web: "Harness", payload: bytes):
    """A ping is answered with its payload, and a valid close is echoed and ends the viewer.

    Args:
        web: Drives the dashboard server.
        payload: The ping's payload.
    """

    async def run():
        sock = await web.upgrade()
        sock.incoming.extend(masked(payload))
        await web.pump()
        assert sock.outgoing == bytes((0x8A, len(payload))) + payload
        assert max(sock.read_sizes) <= 125
        sock.outgoing.clear()
        sock.incoming.extend(masked(b"\x03\xe8bye", 8))
        await web.pump()
        assert sock.outgoing == b"\x88\x05\x03\xe8bye"
        assert sock.closed
        assert not web.server._connections
        assert web.webserver._pending == [None, None]
        await web.close()

    asyncio.run(run())


def test_invalid_close_not_echoed(web: "Harness"):
    """A close with an invalid payload ends the viewer without an echo.

    Args:
        web: Drives the dashboard server.
    """

    async def run():
        sock = await web.upgrade()
        sock.incoming.extend(masked(b"\x03\xe8\xff", 8))
        await web.pump()
        assert sock.closed
        assert not sock.outgoing
        await web.close()

    asyncio.run(run())


def test_single_viewer_and_queue_limits(web: "Harness"):
    """A second viewer is refused, and the viewer's queue keeps only small, recent reports.

    Args:
        web: Drives the dashboard server.
    """

    async def run():
        sock = await web.upgrade()
        second = web.accept(_UPGRADE)
        await web.pump()
        assert b"503" in second.outgoing
        for i in range(10000):
            web.webserver.queue_report(str(i))
        assert web.webserver._pending == ["9998", "9999"]
        await web.pump()
        assert sock.outgoing == b"\x81\x049998\x81\x049999"
        sock.outgoing.clear()
        for value in ("a" * 1025, "é" * 513):
            web.webserver.queue_report(value)
            await web.pump()
            assert not sock.outgoing
        web.webserver.queue_report("é" * 512)
        await web.pump()
        assert len(sock.outgoing) == 1028
        await web.close()
        web.webserver.queue_report("ignored")
        assert web.webserver._pending == [None, None]

    asyncio.run(run())


def test_takeover_replaces_the_open_viewer(web: "Harness"):
    """A takeover upgrade closes the open viewer and becomes the viewer.

    Args:
        web: Drives the dashboard server.
    """

    async def run():
        first = await web.upgrade()
        second = web.accept(_UPGRADE.replace(b"/ws ", b"/ws?takeover=1 "))
        await web.pump()
        assert first.closed
        assert b"101 Switching Protocols" in second.outgoing
        assert not second.closed
        web.webserver.queue_report("after")
        await web.pump()
        assert second.outgoing.endswith(b"\x81\x05after")
        await web.close()

    asyncio.run(run())


def test_control_rate_and_refill_across_wrap(web: "Harness"):
    """Control frames beyond the token budget close the viewer, refilling across tick wrap.

    Args:
        web: Drives the dashboard server.
    """
    web.clock.ticks = web.clock._PERIOD - 100

    async def run():
        sock = await web.upgrade()
        sock.incoming.extend(masked() + masked(opcode=10) + masked() + masked(opcode=10))
        await web.pump()
        web.advance(250)
        sock.incoming.extend(masked())
        await web.pump()
        assert not sock.closed
        web.advance(10000)
        sock.incoming.extend(masked() * 5)
        await web.pump()
        assert sock.closed
        assert sock.outgoing == b"\x8a\x00" * 7
        assert len(sock.incoming) == 4
        await web.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    ("kind", "limit_ms"),
    [("request", 2000), ("frame", 1000), ("write", 1000), ("lifetime", 10 * 60 * 1000)],
)
def test_absolute_and_stalled_deadlines_across_wrap(web: "Harness", kind: str, limit_ms: int):
    """Each deadline closes its connection exactly at its limit, even across tick wrap.

    Args:
        web: Drives the dashboard server.
        kind: Which deadline the connection runs into.
        limit_ms: How long that deadline allows.
    """
    web.clock.ticks = web.clock._PERIOD - 100

    async def run():
        if kind == "request":
            sock = web.accept(b"G")
        elif kind == "write":
            sock = web.accept(_GET)
            sock.write_limit = 0
        else:
            sock = await web.upgrade()
        if kind == "frame":
            # An idle viewer has no frame deadline until a frame begins.
            web.advance(20000)
            await web.pump()
            assert not sock.closed
            sock.incoming.extend(b"\x89")
        await web.pump(15)
        web.advance(limit_ms - 1)
        if kind == "request":
            sock.incoming.extend(b"E")
        await web.pump(1)
        assert not sock.closed
        web.advance(1)
        await web.pump()
        assert sock.closed
        assert not web.server._connections
        await web.close()

    asyncio.run(run())


@pytest.mark.parametrize("data", [_GET, _UPGRADE])
def test_response_deadline_despite_write_progress(web: "Harness", data: bytes):
    """A response trickling out a byte at a time is still cut off at its deadline.

    Args:
        web: Drives the dashboard server.
        data: The request whose response is written slowly.
    """
    web.clock.ticks = web.clock._PERIOD - 100

    async def run():
        sock = web.accept(data)
        sock.write_limit = 1
        await web.pump(15)
        for _ in range(9):
            web.advance(500)
            await web.pump(1)
        web.advance(499)
        await web.pump(1)
        assert not sock.closed
        web.advance(1)
        await web.pump()
        assert sock.closed
        assert not web.server._connections
        await web.close()

    asyncio.run(run())


def test_admission_ceiling_rate_and_slot_cleanup(web: "Harness"):
    """Admission caps open connections and the accept rate, and frees slots as peers leave.

    Args:
        web: Drives the dashboard server.
    """

    async def run():
        first = web.accept(b"")
        second = web.accept(b"")
        excess = web.accept(b"")
        assert len(web.server._connections) == 2
        assert excess.closed
        assert not excess.read_sizes
        first.eof = second.eof = True
        await web.pump()
        for _ in range(2):
            sock = web.accept()
            await web.pump()
            assert b"200" in sock.outgoing
        assert web.accept().closed
        web.advance(500)
        sock = web.accept()
        await web.pump()
        assert b"200" in sock.outgoing
        await web.close()

    asyncio.run(run())


def test_low_heap_stops_work_and_requires_cleanup_before_recovery(
    web: "Harness", monkeypatch: pytest.MonkeyPatch
):
    """Low heap suspends the server; it resumes only after backoff and with headroom.

    Args:
        web: Drives the dashboard server.
        monkeypatch: Scripts free heap and records listener creation.
    """

    async def run():
        sock = await web.upgrade()
        other = web.accept(b"")
        web.webserver.queue_report("pending")
        monkeypatch.setattr(web.module.gc, "mem_free", lambda: 65535)
        web.advance(100)
        web.server._step(web.clock.ticks_ms())
        assert web.server.state == "cooldown"
        assert sock.closed
        assert other.closed
        assert web.listener.closed
        web.server._suspend("memory")
        assert web.server._retry_ms == 5000
        await web.pump()
        assert not web.server._connections
        assert web.webserver._pending == [None, None]
        assert not web.webserver._viewer
        resumes = []
        monkeypatch.setattr(web.module.socket, "socket", lambda: resumes.append(True))
        web.advance(4999)
        web.server._step(web.clock.ticks_ms())
        assert not resumes
        web.advance(1)
        monkeypatch.setattr(web.module.gc, "mem_free", lambda: 98303)
        web.server._step(web.clock.ticks_ms())
        assert web.server._retry_ms == 10000
        assert not resumes
        monkeypatch.setattr(web.module.gc, "mem_free", lambda: 98304)
        monkeypatch.setattr(web.module.socket, "socket", Listener)
        web.advance(10000)
        web.server._step(web.clock.ticks_ms())
        assert web.server.state == "running"
        web.advance(60000)
        web.server._step(web.clock.ticks_ms())
        assert web.server._retry_ms == 5000
        await web.close()

    asyncio.run(run())


@pytest.mark.parametrize(("exception", "state"), _FAILURES)
@pytest.mark.parametrize("where", ["read", "write", "route"])
def test_resource_failures_and_peer_errors(
    web: "Harness", exception: Exception, state: str, where: str
):
    """A failure anywhere in a request closes its connection; only resource failures suspend.

    Args:
        web: Drives the dashboard server.
        exception: The failure injected.
        state: The server's lifecycle state afterwards.
        where: Whether the socket read, the socket write, or the route raises.
    """

    async def fail(_request):
        raise exception

    if where == "route":
        web.webserver._app.get("/fail")(fail)

    async def run():
        sock = web.accept(_GET.replace(b"/ ", b"/fail ") if where == "route" else _GET)
        if where == "read":
            sock.read_error = exception
        elif where == "write":
            sock.write_error = exception
        await web.pump()
        assert sock.closed
        assert not web.server._connections
        assert web.server.state == state
        await web.close()

    asyncio.run(run())


@pytest.mark.parametrize("exception", [pytest.param(TypeError("route bug"), id="type-error")])
def test_unexpected_route_error_stays_within_the_json_protocol(
    web: "Harness", capsys: pytest.CaptureFixture[str], exception: Exception
):
    """A route bug answers 500 and is reported as one JSON error line, not a traceback.

    Args:
        web: Drives the dashboard server.
        capsys: Captures the error line.
        exception: The bug the route raises.
    """

    async def fail(_request):
        raise exception

    web.webserver._app.get("/fail")(fail)

    async def run():
        sock = web.accept(_GET.replace(b"/ ", b"/fail "))
        await web.pump()
        assert sock.outgoing.split(b" ")[1] == b"500"
        assert web.server.state == "running"
        await web.close()

    capsys.readouterr()
    asyncio.run(run())

    assert json_lines(capsys.readouterr().out) == [
        {"event": "error", "component": "dashboard", "message": str(exception)}
    ]


def test_partial_writes_serialize_ping_and_telemetry(web: "Harness"):
    """A pong and a report written a byte at a time never interleave.

    Args:
        web: Drives the dashboard server.
    """

    async def run():
        sock = await web.upgrade()
        sock.write_limit = 1
        web.webserver.queue_report("telemetry")
        sock.incoming.extend(masked(b"ping"))
        await web.pump()
        telemetry = b"\x81\x09telemetry"
        pong = b"\x8a\x04ping"
        assert sock.outgoing in (telemetry + pong, pong + telemetry)
        await web.close()

    asyncio.run(run())


@pytest.mark.parametrize("blocked_by", ["lock", "slow_peer"])
def test_websocket_write_deadline_includes_lock_wait(web: "Harness", blocked_by: str):
    """A write's deadline counts time spent waiting for the write lock.

    Args:
        web: Drives the dashboard server.
        blocked_by: Whether a held lock or a slow peer stalls the pong.
    """

    async def run():
        sock = await web.upgrade()
        peer = web.server._connections[0]
        if blocked_by == "lock":
            await peer.lock.acquire()
        else:
            sock.write_limit = 1
        sock.incoming.extend(masked(b"a" * 125))
        await web.pump(1)
        for _ in range(3):
            web.advance(300)
            await web.pump(1)
        assert not sock.closed
        web.advance(100)
        await web.pump()
        assert sock.closed
        assert not web.server._connections
        if blocked_by == "lock":
            peer.lock.release()
        else:
            assert not peer.lock.locked()
        await web.close()

    asyncio.run(run())


def test_cancellation_before_handler_runs_and_backoff_cap(web: "Harness"):
    """A connection closed before its handler starts is released, and backoff caps at a minute.

    Args:
        web: Drives the dashboard server.
    """

    async def run():
        sock = web.accept()
        await web.close()
        assert sock.closed
        assert not sock.read_sizes
        assert not web.server._connections
        for _ in range(8):
            web.server.state = "running"
            web.server._suspend("memory")
        assert web.server._retry_ms == 60000

    asyncio.run(run())


def test_suspension_joins_partial_writes_and_lock_waiters(web: "Harness"):
    """Suspension ends a stalled writer and its lock waiters, leaving no task behind.

    Args:
        web: Drives the dashboard server.
    """

    async def run():
        sock = await web.upgrade()
        sock.write_limit = 1
        web.webserver.queue_report("a" * 100)
        sock.incoming.extend(masked(b"ping"))
        await web.pump(5)
        assert web.server._connections[0].lock.locked()
        web.webserver.queue_report("pending")
        await web.close()
        assert sock.closed
        assert not web.server._connections
        assert not web.webserver._viewer
        assert web.webserver._pending == [None, None]
        assert asyncio.all_tasks() == {asyncio.current_task()}

    asyncio.run(run())


@pytest.mark.parametrize("close_error", [None, OSError(errno.EIO)], ids=["closes", "close-fails"])
@pytest.mark.parametrize("stage", ["connection", "handler"])
def test_allocation_failure_during_admission_closes_unowned_socket(
    web: "Harness", monkeypatch: pytest.MonkeyPatch, stage: str, close_error: OSError | None
):
    """The socket is released, and a failing close never replaces the memory failure.

    Args:
        web: Drives the dashboard server.
        monkeypatch: Makes the chosen admission stage run out of memory.
        stage: Whether building the connection or starting its handler fails.
        close_error: What closing the socket raises, or None to close cleanly.
    """

    def fail(*_args):
        raise MemoryError

    async def run():
        supervisor = asyncio.create_task(web.server.run())
        sock = Socket(_GET)
        sock.close_error = close_error
        with monkeypatch.context() as patch:
            if stage == "connection":
                patch.setattr(web.module, "_Connection", fail)
            else:
                patch.setattr(asyncio, "create_task", fail)
            web.listener.pending.append(sock)
            await web.pump()
        assert sock.closed
        assert not web.server._connections
        assert (web.server.state, web.server.reason) == ("cooldown", "memory")
        supervisor.cancel()
        with pytest.raises(asyncio.CancelledError):
            await supervisor

    asyncio.run(run())


@pytest.mark.parametrize(
    ("exception", "reason"), [(MemoryError(), "memory"), (OSError(errno.ENOBUFS), "socket")]
)
@pytest.mark.parametrize("operation", ["bind", "accept"])
def test_listener_failure_recovers_and_releases_the_listener(
    web: "Harness",
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    exception: Exception,
    reason: str,
):
    """A listener that fails to bind or to accept is closed, and a new one listens later.

    Args:
        web: Drives the dashboard server.
        monkeypatch: Makes the listener operation fail, then restores a working listener.
        operation: The listener method that raises.
        exception: What it raises.
        reason: The cooldown reason the server records.
    """
    listener = Listener()

    def fail(*_args):
        raise exception

    async def run():
        web.server._close()
        web.server.state = "stopped"
        monkeypatch.setattr(web.module.socket, "socket", lambda: listener)
        monkeypatch.setattr(listener, operation, fail)
        supervisor = asyncio.create_task(web.server.run())
        await web.pump()
        assert listener.closed
        assert (web.server.state, web.server.reason) == ("cooldown", reason)
        assert web.server._listener is None
        monkeypatch.setattr(web.module.socket, "socket", Listener)
        web.advance(5000)
        await web.pump()
        assert web.server.state == "running"
        supervisor.cancel()
        with pytest.raises(asyncio.CancelledError):
            await supervisor
        assert web.server._listener is None

    asyncio.run(run())


@pytest.mark.parametrize(
    ("data", "viewing"),
    [
        pytest.param(_GET[:5], False, id="partial-request"),
        pytest.param(_UPGRADE, True, id="viewer"),
    ],
)
def test_cancelled_supervisor_closes_and_joins_open_connections(
    web: "Harness", data: bytes, viewing: bool
):
    """Cancelling the server ends every open handler before it reports stopped.

    Args:
        web: Drives the dashboard server.
        data: What the open connection has sent.
        viewing: Whether that connection is the WebSocket viewer.
    """

    async def run():
        supervisor = asyncio.create_task(web.server.run())
        sock = Socket(data)
        web.listener.pending.append(sock)
        await web.pump()
        assert web.server._connections
        assert bool(web.webserver._viewer) is viewing
        supervisor.cancel()
        with pytest.raises(asyncio.CancelledError):
            await supervisor
        assert sock.closed
        assert web.listener.closed
        assert not web.server._connections
        assert not web.webserver._viewer
        assert web.server.state == "stopped"
        assert asyncio.all_tasks() == {asyncio.current_task()}

    asyncio.run(run())


@pytest.mark.parametrize(("exception", "state"), _FAILURES)
def test_sender_failure_releases_viewer_and_queue(web: "Harness", exception: Exception, state: str):
    """A failed report write drops the viewer and its queue; only resource failures suspend.

    Args:
        web: Drives the dashboard server.
        exception: What the viewer's socket write raises.
        state: The server's lifecycle state afterwards.
    """

    async def run():
        sock = await web.upgrade()
        sock.write_error = exception
        web.webserver.queue_report("report")
        await web.pump()
        assert sock.closed
        assert not web.webserver._viewer
        assert web.webserver._pending == [None, None]
        assert not web.server._connections
        assert web.server.state == state
        await web.close()

    asyncio.run(run())


def test_real_socket_reconnect_churn(
    load_application: Callable[..., SimpleNamespace], monkeypatch: pytest.MonkeyPatch
):
    """Alternating real HTTP and WebSocket clients each connect cleanly and leave nothing behind.

    Args:
        load_application: Boots the firmware application.
        monkeypatch: Runs the webserver on the real clock.
    """
    boot = load_application()
    real_time = SimpleNamespace(
        ticks_ms=lambda: int(time.monotonic() * 1000),
        ticks_diff=lambda newer, older: newer - older,
        ticks_add=lambda ticks, delta: ticks + delta,
    )
    monkeypatch.setattr(boot.webserver_module, "time", real_time)
    webserver = boot.application._webserver
    server = webserver._server

    async def run():
        supervisor = asyncio.create_task(server.run())
        try:
            while server._listener is None:
                await asyncio.sleep(0.01)
            port = server._listener.getsockname()[1]
            for index in range(8):
                reader, writer = await asyncio.open_connection("127.0.0.1", port)
                writer.write(_GET if index % 2 else _UPGRADE)
                await writer.drain()
                assert (b"200" if index % 2 else b"101") in await reader.readline()
                while await reader.readline() != b"\r\n":
                    pass
                if index % 2:
                    assert await reader.read() == b"dashboard"
                else:
                    header = await reader.readexactly(2)
                    assert header[0] == 0x81
                    await reader.readexactly(header[1])
                    writer.write(masked(b"bye", 9) + masked(b"", 8))
                    await writer.drain()
                    assert await reader.read() == b"\x8a\x03bye\x88\x00"
                writer.close()
                await writer.wait_closed()
                await asyncio.sleep(0.5)
                assert not server._connections
                assert not webserver._viewer
                assert webserver._pending == [None, None]
        finally:
            supervisor.cancel()
            with pytest.raises(asyncio.CancelledError):
                await supervisor
        assert server._listener is None
        assert not server._connections

    asyncio.run(asyncio.wait_for(run(), 15))


@pytest.fixture
def web(load_application: Callable[..., SimpleNamespace]) -> "Harness":
    """A harness around a running dashboard server with a fake listener.

    Args:
        load_application: Boots the firmware application.

    Returns:
        The harness.
    """
    return Harness(load_application())


class Socket:
    """Nonblocking socket with bounded reads and injected failures."""

    def __init__(self, data: bytes) -> None:
        """Initialize the peer buffers and fault controls.

        Args:
            data: Everything the peer has sent so far.
        """
        self.incoming = bytearray(data)
        self.outgoing = bytearray()
        self.closed = False
        self.eof = False
        self.read_error = None
        self.write_error = None
        self.close_error = None
        self.write_limit = 512
        self.read_sizes = []
        self.consumed = 0

    def setblocking(self, value: bool):
        """Require nonblocking access.

        Args:
            value: The blocking mode requested; must be False.
        """
        assert value is False

    def recv(self, count: int) -> bytes:
        """Consume no more than the requested bytes.

        Args:
            count: The most bytes to return.

        Returns:
            The bytes read, or ``b""`` once the socket is closed or at EOF.

        Raises:
            self.read_error: The injected read failure, when armed.
            OSError: EAGAIN when no data is waiting.
        """
        self.read_sizes.append(count)
        if self.read_error:
            raise self.read_error
        if self.closed or self.eof:
            return b""
        if not self.incoming:
            raise OSError(errno.EAGAIN)
        data = bytes(self.incoming[:count])
        del self.incoming[:count]
        self.consumed += len(data)
        return data

    def send(self, data: bytes) -> int:
        """Record a partial write, report would-block when nothing fits, or raise a failure.

        Args:
            data: The bytes to write.

        Returns:
            How many bytes were written, at most ``write_limit``.

        Raises:
            self.write_error: The injected write failure, when armed.
            OSError: EAGAIN when ``write_limit`` is zero.
        """
        if self.write_error:
            raise self.write_error
        if not self.write_limit:
            raise OSError(errno.EAGAIN)
        count = min(len(data), self.write_limit)
        self.outgoing.extend(data[:count])
        return count

    def close(self):
        """Record socket release, then raise any injected close failure.

        Raises:
            self.close_error: The injected close failure, when armed.
        """
        self.closed = True
        if self.close_error:
            raise self.close_error


class Listener:
    """Listener with scripted peers and checked bind settings."""

    def __init__(self) -> None:
        """Start with no waiting peers."""
        self.pending = []
        self.closed = False

    def setsockopt(self, *_args: int):
        """Allow listener option setup.

        Args:
            *_args: The socket option level, name, and value.
        """

    def setblocking(self, value: bool):
        """Require nonblocking admission.

        Args:
            value: The blocking mode requested; must be False.
        """
        assert value is False

    def bind(self, _address: tuple):
        """Allow address binding.

        Args:
            _address: The address to bind.
        """

    def listen(self, backlog: int):
        """Check the bounded listen backlog.

        Args:
            backlog: The backlog requested; must be 2.
        """
        assert backlog == 2

    def accept(self) -> tuple[Socket, tuple[str, int]]:
        """Return one waiting peer or report would-block.

        Returns:
            The next waiting socket and its peer address.

        Raises:
            OSError: EAGAIN when no peer is waiting.
        """
        if not self.pending:
            raise OSError(errno.EAGAIN)
        return self.pending.pop(0), ("peer", 123)

    def close(self):
        """Record listener release."""
        self.closed = True


class Harness:
    """Drive the application's real Microdot routes with manual time."""

    def __init__(self, boot: SimpleNamespace) -> None:
        """Use application routes with a fake listener.

        Args:
            boot: The loaded application, its modules, and its fake clock.
        """
        self.clock = boot.time
        self.webserver = boot.application._webserver
        self.module = boot.webserver_module
        self.server = self.webserver._server
        self.listener = Listener()
        self.server._listener = self.listener
        self.server.state = "running"

    def advance(self, milliseconds: int):
        """Move the device clock, including tick wrap.

        Args:
            milliseconds: How far to move it.
        """
        self.clock.ticks = self.clock.ticks_add(self.clock.ticks, milliseconds)

    def accept(self, data: bytes = _GET) -> Socket:
        """Pass one socket through actual admission checks.

        Args:
            data: Everything the peer sends first.

        Returns:
            The peer's socket, admitted or closed by admission.
        """
        sock = Socket(data)
        self.listener.pending.append(sock)
        self.server._step(self.clock.ticks_ms())
        return sock

    async def pump(self, turns: int = 200):
        """Run peer tasks and reap completed handlers.

        Args:
            turns: How many times to yield to the event loop.
        """
        for _ in range(turns):
            await asyncio.sleep(0)
            await self.server._reap()

    async def upgrade(self) -> Socket:
        """Complete a handshake and consume the application greeting.

        Returns:
            The viewer's socket, with its outgoing buffer cleared.
        """
        sock = self.accept(_UPGRADE)
        await self.pump()
        assert b"101 Switching Protocols" in sock.outgoing
        assert b'"event": "connected"' in sock.outgoing
        sock.outgoing.clear()
        return sock

    async def close(self):
        """Suspend and join remaining dashboard work."""
        self.server._suspend("worker")
        await self.pump()


def masked(payload: bytes = b"", opcode: int = 9) -> bytes:
    """Encode one final, masked client frame.

    Args:
        payload: The frame's payload, at most 125 bytes.
        opcode: The frame's opcode; the default is a ping.

    Returns:
        The encoded frame.
    """
    key = b"\x01\x02\x03\x04"
    return (
        bytes((128 | opcode, 128 | len(payload)))
        + key
        + bytes(value ^ key[index % 4] for index, value in enumerate(payload))
    )
