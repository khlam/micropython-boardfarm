# cpython-packages
Shared host-CPython packages. Installed editable into the `pytest` and
`viz` Docker stage venvs via uv workspace. Never frozen onto the device
— for MCU code see [`../firmware-packages/`](../firmware-packages/).


## Package Layout
```
<pkg>/
  <pkg>/            host CPython code (installed into the venv)
  tests/            host pytest (if any)
  pyproject.toml    uv workspace member metadata
  README.md         usage, public API
```

`micropython_stubs` is the one exception: its modules also re-export at
the top level via hatch `force-include`, so host tests resolve
`import machine` exactly as on-device firmware does.


## Packages
| Package | What it does |
|---|---|
| [serial_over_web](serial_over_web/) | Shared FastAPI dashboard server. Tails `/dev/ttyACM0`, validates JSON lines, fans out over `/ws` WebSocket. Per-project static dashboards mount on top. |
| [micropython_stubs](micropython_stubs/) | Host shims for the MicroPython builtins firmware code imports (`machine`, `neopixel`, `ujson`, `ustruct`, `utime`, `micropython`). Lets host pytest exercise firmware without a board attached. |


## Notes
- Pylance (optional) resolves `import <pkg>` via `python.analysis.extraPaths`
in [.vscode/settings.json](../.vscode/settings.json) pointing at each
package's root.
- The `viz` Docker stage installs only `serial_over_web` (`uv sync --group viz`).
The `pytest` stage installs the full set (`uv sync --group test`).
- Coverage is configured for `serial_over_web` in the root
[pyproject.toml](../pyproject.toml); `micropython_stubs` is excluded
because its job is to be replaced by real MicroPython on the device.


## Tests
From the repo root:
```
docker compose run --rm --build pytest /cpython-packages
docker compose run --rm pytest /cpython-packages/serial_over_web/tests
```
`micropython_stubs` has no standalone tests — every firmware package's
host pytest suite exercises it.

`/cpython-packages/serial_over_web/` is a bind-mount inside the test container (mapped from the host by the root [docker-compose.yaml](../docker-compose.yaml) at runtime, read-only), so edits take effect without rebuilding the image.
