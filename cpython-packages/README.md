# cpython-packages
Shared host-CPython packages. Installed editable into the `pytest` and
`viz` Docker stage venvs via uv workspace. Never frozen onto the device;
for MCU code see [`../firmware-packages/`](../firmware-packages/).


## Package Layout
```
<pkg>/
  <pkg>/            host CPython code (installed into the venv)
  tests/            host pytest (if any)
  pyproject.toml    uv workspace member metadata
  README.md         usage, public API
```

`micropython_stubs` is the one exception: hatch `force-include` also ships
its replacement modules at the wheel root, so host tests resolve `import machine`
exactly as on-device firmware does.


## Packages
| Package | What it does |
|---|---|
| [serial_over_web](serial_over_web/) | Shared FastAPI dashboard server. Tails `/dev/ttyACM0`, validates JSON lines, fans out over `/ws` WebSocket. Per-project static dashboards mount on top. |
| [micropython_stubs](micropython_stubs/) | Test replacements for the MicroPython modules firmware code imports (`machine`, `neopixel`, `ujson`, `ustruct`, `utime`, `micropython`). Lets host CPython pytest run MicroPython code on CPython by providing test versions of MicroPython-only modules. This enables testing firmware logic separately from firmware-and-hardware performance testing. |


## micropython_stubs
`micropython_stubs` is a tests-only uv workspace member. The `pytest`
Docker stage installs it into the test venv, where its files are available
both as `micropython_stubs.<module>` and as MicroPython-style top-level
imports.

```
micropython_stubs/
  pyproject.toml          uv workspace metadata plus hatch force-include
  micropython_stubs/
    __init__.py           package marker
    machine.py            fake Pin, I2C, SoftI2C, and UART
    neopixel.py           fake NeoPixel strip with recorded writes
    ujson.py              CPython json exported as ujson
    ustruct.py            CPython struct exported as ustruct
    utime.py              no-op sleep_ms plus monotonic ticks
    micropython.py        const(x) returns x
    asyncio_extras.py     MicroPython-only asyncio names, installed onto stdlib
    testing.py            shared fakes and firmware main.py AST helpers
```

Replacement module behavior:
- `machine.py` records every `Pin(...)` construction in
  `pin_constructions`, routes I2C reads and writes to devices registered
  with `machine.register_device(addr, dev)`, feeds `UART.readline()` from byte
  lines queued with `machine.feed_uart(...)`, and feeds non-blocking
  `UART.any()` / `UART.read()` / `UART.readinto()` from
  `machine.feed_uart_bytes(...)`.
- `machine.UART` also records constructions in `uart_constructions`, keeps
  every constructor keyword in `config`, and implements `irq()` / `deinit()`.
  `feed_uart_bytes(...)` runs each UART's `IRQ_RXIDLE` handler after queueing,
  which is how an interrupt-driven driver wakes on the host; pass
  `notify=False` to make the driver fall back to its own timeout instead.
- `neopixel.py` records `NeoPixel` instances and appends the current LED 0
  color to `writes` on each `write()`.
- `ujson.py` and `ustruct.py` re-export CPython's `json` and `struct`
  APIs used by firmware tests.
- `utime.py` makes `sleep_ms()` a no-op and implements `ticks_ms()` /
  `ticks_diff()` with host time.
- `micropython.py` exposes `const(x)` as an identity function.
- `asyncio_extras.py` supplies `ThreadSafeFlag`, `wait_for_ms`, and `sleep_ms`
  — the names MicroPython adds to `asyncio` — and `install(monkeypatch)` puts
  them on the stdlib module for the duration of a test.
- `testing.py` provides `FakeTime`, `FakeStatus`, and helpers that load
  selected assignments/functions from a firmware `main.py` into a test
  namespace.

Reset mutable test-module state in autouse fixtures with `machine.reset()` and
`neopixel.reset()`. Add new top-level replacements by creating the module under
`micropython_stubs/micropython_stubs/` and adding it to
`tool.hatch.build.targets.wheel.force-include` in
[`micropython_stubs/pyproject.toml`](micropython_stubs/pyproject.toml). A name
the stdlib already owns — `asyncio` — cannot be replaced that way, because the
stdlib module wins on `sys.path`; extend the real module from a fixture as
`asyncio_extras` does.


## Notes
- Pylance (optional) resolves `import <pkg>` via `python.analysis.extraPaths`
in [.vscode/settings.json](../.vscode/settings.json) pointing at each
package's root.
- The `viz` Docker stage installs only `serial_over_web` (`uv sync --group viz`).
The `pytest` stage installs the full set (`uv sync --group test`).
- Coverage is configured for `serial_over_web` in the root
[pyproject.toml](../pyproject.toml); `micropython_stubs` is excluded
because its job is to be replaced by real MicroPython on the device.
- The projects served by the `serial_over_web` dashboard and exercised
against these stubs live under [`../projects/`](../projects/README.md).


## Tests
From the repo root:
```
docker compose run --rm --build pytest /cpython-packages
docker compose run --rm pytest /cpython-packages/serial_over_web/tests
```
`micropython_stubs` has no standalone tests; every firmware package's
host pytest suite exercises it.

`/cpython-packages/serial_over_web/` is a bind-mount inside the test container (mapped from the host by the root [docker-compose.yaml](../docker-compose.yaml) at runtime, read-only), so edits take effect without rebuilding the image.
