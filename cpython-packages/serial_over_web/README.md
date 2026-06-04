# serial_over_web

Shared host FastAPI dashboard. Tails a board's serial port and broadcasts
every valid JSON line to all connected WebSocket clients on `/ws`. Each
project supplies its own static dashboard (HTML/JS); this is the server
that feeds it. CPython only — never lands on the microcontroller.

## Layout
```
cpython-packages/serial_over_web/
  pyproject.toml      uv workspace member; pins fastapi / uvicorn / pyserial
  serial_over_web/
    __init__.py       docstring only
    app.py            FastAPI app, serial reader thread, /ws broadcaster
  tests/              host pytest against monkeypatched serial
```

## Usage
The viz Docker stage runs the module via uvicorn:
```
uvicorn serial_over_web.app:app --host 0.0.0.0 --port 18501
```

Endpoints exposed by `serial_over_web.app:app`:
- `GET /` — serves `index.html` from `$STATIC_DIR` (per-project
  dashboard; the viz Docker stage sets `STATIC_DIR=/app/static` and
  populates it from `${VIZ_DIR}/static`).
- `WS  /ws` — sends a one-time `{event: connected|disconnected, port, error}`
  hello frame, then forwards every JSON line read from the serial port.

Environment:
- `SERIAL_PORT` — defaults to `/dev/ttyACM0`; override via compose
  `environment:` to point at a different device.
- `STATIC_DIR` — directory of the static dashboard to serve; falls back
  to `static/` next to `app.py` when unset.

## Notes
Named `serial_over_web` (not `serial`) because `import serial` inside
this module resolves to `pyserial`; a package named `serial` would
shadow it and break the module at import time.

A project's `viz/static/index.html` opens `ws://<host>:18501/ws` and
renders whatever schema its firmware emits. The server doesn't know or
care about the schema — it only validates that each line is parseable
JSON before forwarding. The split is deliberate: one server, per-project
visualizations (Plotly line chart for distance-stream, 3D orientation +
multi-trace plots for gyro-stream).

The `StaticFiles` mount in `app.py` is guarded by `STATIC_DIR.is_dir()`
so the package imports cleanly in the test image without a per-project
`static/` sitting next to it.

## Tests
From the repo root:
```
docker compose run --rm --build test -- /cpython-packages/serial_over_web/tests
```
The root `docker-compose.yaml` mounts this directory into the test
container as `/cpython-packages/serial_over_web:ro`. Pure host pytest
against monkeypatched serial.
