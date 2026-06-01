"""Host CPython FastAPI dashboard that streams a board's serial JSON output over WebSocket.

Reads JSON-per-line samples from the serial port in a background thread,
parses + filters them, and broadcasts every valid line to all connected
WebSocket clients on `/ws`. The static dashboard is served from the
directory pointed to by the `STATIC_DIR` env var, falling back to
`static/` next to this file when unset.
"""

import asyncio
import json
import os
import threading
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Literal

import serial
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict

SERIAL_PORT = os.environ.get("SERIAL_PORT", "/dev/ttyACM0")
SERIAL_BAUD = 115200
QUEUE_MAXSIZE = 2000
STATIC_DIR = Path(os.environ.get("STATIC_DIR", Path(__file__).parent / "static"))
# Tight retry so the dashboard picks up a reflashed/replugged board
# within ~200 ms of it re-enumerating.
_RECONNECT_DELAY_S = 0.2

__all__ = ["app"]


class _SerialState(BaseModel):
    """Mutable snapshot of the serial port's connection state."""

    model_config = ConfigDict(validate_assignment=True)
    connected: bool = False
    error: str | None = None
    port: str = ""


class _SerialEvent(BaseModel):
    """A serialisable connection-state event broadcast to WebSocket clients."""

    model_config = ConfigDict(frozen=True)
    event: Literal["connected", "disconnected"]
    port: str
    error: str | None = None


_state = _SerialState(port=SERIAL_PORT)
_clients: set[WebSocket] = set()


def _safe_put(queue: asyncio.Queue, text: str) -> None:
    """Enqueue `text` if there is room; silently drop it if the queue is full."""
    with suppress(asyncio.QueueFull):
        queue.put_nowait(text)


def _schedule(loop: asyncio.AbstractEventLoop, queue: asyncio.Queue, text: str) -> None:
    """Hand `text` to the asyncio loop from a worker thread."""
    with suppress(RuntimeError):
        loop.call_soon_threadsafe(_safe_put, queue, text)


def _pump_serial(ser: serial.Serial, loop: asyncio.AbstractEventLoop, queue: asyncio.Queue) -> None:
    """Read lines from `ser` and forward every valid JSON line to the queue."""
    while True:
        line = ser.readline()
        if not line:
            continue
        text = line.decode("utf-8", errors="replace").strip()
        if not text:
            continue
        try:
            json.loads(text)
        except ValueError:
            continue
        _schedule(loop, queue, text)


def _serial_thread(loop: asyncio.AbstractEventLoop, queue: asyncio.Queue) -> None:
    """Background-thread main loop: open the serial port and pump samples.

    Reconnects on `SerialException` / `OSError` so that unplug/replug or
    reflash recovers without restarting the process.
    """
    while True:
        try:
            # serial_for_url accepts both device paths and socket:// URLs (macOS TCP bridge).
            with serial.serial_for_url(
                SERIAL_PORT,
                SERIAL_BAUD,
                timeout=0.1,
                dsrdtr=False,
                rtscts=False,
            ) as ser:
                _state.connected = True
                _state.error = None
                _schedule(
                    loop,
                    queue,
                    _SerialEvent(event="connected", port=SERIAL_PORT).model_dump_json(),
                )
                _pump_serial(ser, loop, queue)
        except (serial.SerialException, OSError) as e:
            _state.connected = False
            _state.error = str(e)
            _schedule(
                loop,
                queue,
                _SerialEvent(
                    event="disconnected", port=SERIAL_PORT, error=str(e)
                ).model_dump_json(),
            )
            time.sleep(_RECONNECT_DELAY_S)


async def _broadcaster(queue: asyncio.Queue) -> None:
    """Fan out every queued line to all connected WebSocket clients."""
    while True:
        text = await queue.get()
        dead = []
        for ws in list(_clients):
            try:
                await ws.send_text(text)
            except (WebSocketDisconnect, RuntimeError):
                dead.append(ws)
        for ws in dead:
            _clients.discard(ws)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Start the serial reader + broadcaster on app startup, cancel on shutdown."""
    queue: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_MAXSIZE)
    loop = asyncio.get_running_loop()
    threading.Thread(target=_serial_thread, args=(loop, queue), daemon=True).start()
    bcast = asyncio.create_task(_broadcaster(queue))
    try:
        yield
    finally:
        bcast.cancel()


app = FastAPI(lifespan=lifespan)


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    """Send the current serial-state hello frame, then forward broadcasts."""
    await ws.accept()
    hello = _SerialEvent(
        event="connected" if _state.connected else "disconnected",
        port=_state.port,
        error=_state.error,
    )
    await ws.send_text(hello.model_dump_json())
    _clients.add(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        _clients.discard(ws)


# Only mount when static/ exists beside this file. The viz Docker stage
# COPYs each project's static dashboard next to this module; the test stage
# does not, and an unconditional mount would fail at import time.
if STATIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
