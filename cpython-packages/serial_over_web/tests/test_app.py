"""Host CPython pytest tests for the FastAPI viz dashboard.

Logic-only — `serial.serial_for_url` is monkey-patched away so the lifespan
thread never touches the real serial port. Payloads are project-agnostic; the
per-project JSON schemas live under projects/<p>/tests/.
"""

import asyncio
import contextlib
import importlib
import json
import sys

import pytest
import serial
from fastapi import WebSocketDisconnect
from fastapi.testclient import TestClient

from serial_over_web import app


def test_safe_put_drops_on_full_queue():
    queue: asyncio.Queue = asyncio.Queue(maxsize=1)
    queue.put_nowait("first")
    # Must not raise even though the queue is at capacity.
    app._safe_put(queue, "second")
    assert queue.get_nowait() == "first"
    assert queue.empty()


def test_pump_serial_forwards_valid_json_and_drops_garbage(monkeypatch):
    captured: list[str] = []
    # Bypass the asyncio threading: capture what _pump_serial would queue.
    monkeypatch.setattr(app, "_schedule", lambda _loop, _queue, text: captured.append(text))

    ser = _FakeSerial(
        [
            b'{"t": 1, "value": 100}\n',
            b"not json\n",
            b"\n",
            b"",
            b'{"t": 2, "value": null}\n',
        ]
    )
    with pytest.raises(StopIteration):
        app._pump_serial(ser, loop=None, queue=None)

    assert captured == [
        '{"t": 1, "value": 100}',
        '{"t": 2, "value": null}',
    ]


def test_pump_serial_decodes_non_utf8_replacement(monkeypatch):
    """Garbled bytes survive decode (errors=replace) and then fail JSON parse."""
    captured: list[str] = []
    monkeypatch.setattr(app, "_schedule", lambda _loop, _queue, text: captured.append(text))
    ser = _FakeSerial([b"\xff\xfe not json \n", b'{"ok": true}\n'])
    with pytest.raises(StopIteration):
        app._pump_serial(ser, loop=None, queue=None)
    assert captured == ['{"ok": true}']


def test_websocket_sends_hello_frame_on_connect(monkeypatch):
    """Connecting to /ws yields a single hello frame with port + state."""

    def _always_fails(*_args, **_kwargs):
        raise serial.SerialException("test: no port")

    # Keep the lifespan's serial thread from touching the real port.
    monkeypatch.setattr(app.serial, "serial_for_url", _always_fails)

    with TestClient(app.app) as client, client.websocket_connect("/ws") as ws:
        hello = json.loads(ws.receive_text())
        assert hello["event"] in {"connected", "disconnected"}
        assert hello["port"] == app.SERIAL_PORT
        assert "error" in hello


def test_broadcaster_fans_out_to_live_clients():
    sent: list[str] = []

    class _WS:
        async def send_text(self, text):
            sent.append(text)

    ws = _WS()
    app._clients.add(ws)
    try:
        asyncio.run(_drain_broadcaster_once("ping")(lambda: bool(sent), lambda: None))
    finally:
        app._clients.discard(ws)
    assert sent == ["ping"]


def test_broadcaster_discards_disconnected_clients():
    class _DeadWS:
        async def send_text(self, _text):
            raise WebSocketDisconnect

    dead = _DeadWS()
    app._clients.add(dead)
    try:
        still_present = asyncio.run(
            _drain_broadcaster_once("ping")(
                lambda: dead not in app._clients,
                lambda: dead in app._clients,
            )
        )
    finally:
        app._clients.discard(dead)
    assert still_present is False


def test_broadcaster_drops_clients_with_runtime_error():
    # RuntimeError (typically loop-closed) is treated the same as a disconnect.
    class _ClosedWS:
        async def send_text(self, _text):
            raise RuntimeError("loop closed")

    bad = _ClosedWS()
    app._clients.add(bad)
    try:
        still_present = asyncio.run(
            _drain_broadcaster_once("ping")(
                lambda: bad not in app._clients,
                lambda: bad in app._clients,
            )
        )
    finally:
        app._clients.discard(bad)
    assert still_present is False


def test_serial_thread_emits_connected_event_when_port_opens(monkeypatch):
    captured: list[str] = []
    monkeypatch.setattr(app, "_schedule", lambda _loop, _q, text: captured.append(text))

    monkeypatch.setattr(app.serial, "serial_for_url", lambda *_a, **_kw: _FakeSer())
    # Raise a non-(OSError, SerialException) sentinel so the outer except misses it.
    monkeypatch.setattr(
        app, "_pump_serial", lambda *_a, **_kw: (_ for _ in ()).throw(_StopThreadError())
    )

    with pytest.raises(_StopThreadError):
        app._serial_thread(loop=None, queue=None)

    assert app._state.connected is True
    assert app._state.error is None
    assert any(json.loads(m).get("event") == "connected" for m in captured)


def test_serial_thread_passes_socket_url_through(monkeypatch):
    """A socket:// SERIAL_PORT reaches serial_for_url verbatim (macOS TCP bridge)."""
    seen: list[str] = []

    def _capture(url, *_a, **_kw) -> _FakeSer:
        seen.append(url)
        return _FakeSer()

    monkeypatch.setattr(app, "SERIAL_PORT", "socket://host.docker.internal:5555")
    monkeypatch.setattr(app, "_schedule", lambda *_a, **_kw: None)
    monkeypatch.setattr(app.serial, "serial_for_url", _capture)
    monkeypatch.setattr(
        app, "_pump_serial", lambda *_a, **_kw: (_ for _ in ()).throw(_StopThreadError())
    )

    with pytest.raises(_StopThreadError):
        app._serial_thread(loop=None, queue=None)

    assert seen == ["socket://host.docker.internal:5555"]


def test_static_mount_attached_when_static_dir_exists(monkeypatch, tmp_path):
    monkeypatch.setenv("STATIC_DIR", str(tmp_path))
    # Re-import so the module-level `if STATIC_DIR.is_dir()` re-evaluates.
    monkeypatch.delitem(sys.modules, "serial_over_web.app", raising=False)
    fresh = importlib.import_module("serial_over_web.app")
    assert any(getattr(r, "name", None) == "static" for r in fresh.app.routes)


class _FakeSerial:
    """Yields a fixed list of lines from `readline()`, then raises StopIteration.

    `_pump_serial` is `while True: line = ser.readline()`. Exhausting the
    canned list raises StopIteration, which propagates out of the loop —
    that's the test's exit signal.
    """

    def __init__(self, lines) -> None:
        self._iter = iter(lines)

    def readline(self):
        return next(self._iter)


class _FakeSer:
    """Context-manager stub returned by serial_for_url in thread tests."""

    def __enter__(self) -> "_FakeSer":
        return self

    def __exit__(self, *_) -> bool:
        return False


class _StopThreadError(Exception):
    """Sentinel raised inside the thread to escape the outer `while True`."""


def _drain_broadcaster_once(queue_text):
    """Return an async runner that drives _broadcaster once.

    Pushes `queue_text` through _broadcaster, yields until `sent_event()`
    (or 50 ticks), then cancels and returns `post_check()`.
    """

    async def runner(sent_event, post_check):
        queue: asyncio.Queue = asyncio.Queue()
        task = asyncio.create_task(app._broadcaster(queue))
        await queue.put(queue_text)
        for _ in range(50):
            if sent_event():
                break
            await asyncio.sleep(0)
        # One extra tick so the post-except dead-client cleanup runs.
        await asyncio.sleep(0)
        result = post_check()
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        return result

    return runner
