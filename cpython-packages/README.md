# cpython-packages
Shared host-CPython packages. Installed editable into the `pytest`
Docker stage venv via uv workspace. Never frozen onto the device
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
| [micropython_stubs](micropython_stubs/) | Host shims for the MicroPython builtins firmware code imports (`machine`, `neopixel`, `ujson`, `ustruct`, `utime`, `micropython`). Lets host pytest exercise firmware without a board attached. |


## Notes
- Pylance (optional) resolves `import <pkg>` via `python.analysis.extraPaths`
in [.vscode/settings.json](../.vscode/settings.json) pointing at each
package's root.
- The `pytest` Docker stage installs the full workspace (`uv sync --group test`).
- `micropython_stubs` is excluded from coverage in the root
[pyproject.toml](../pyproject.toml) because its job is to be replaced by real
MicroPython on the device.


## Tests
`micropython_stubs` has no standalone tests — every firmware package's
host pytest suite exercises it. Run the full suite from the repo root:
```
docker compose up pytest --build --exit-code-from pytest
```
