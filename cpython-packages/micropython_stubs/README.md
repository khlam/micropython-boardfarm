# micropython_stubs

Host shims for the MicroPython-only modules firmware code imports
(`machine`, `neopixel`, `ujson`, `ustruct`, `utime`, `micropython`).
Lets host pytest import firmware code and assert what it did, without a
board attached.

## Layout
```
cpython-packages/micropython_stubs/
  pyproject.toml          uv workspace member; force-include re-ships
                          each shim at the wheel root so `import machine`
                          resolves top-level in the test venv
  micropython_stubs/
    __init__.py           empty (marks the dir as a package)
    machine.py            fake Pin / I2C / SoftI2C
    neopixel.py           fake NeoPixel, records every write()
    ujson.py              re-exports CPython's json
    ustruct.py            re-exports CPython's struct
    utime.py              sleep_ms = no-op; ticks_ms via time.monotonic
    micropython.py        const(x) → x
```

## Usage
- `machine.py` — fake `Pin`, `I2C`, `SoftI2C`. Records every `Pin(...)`
  call in `pin_constructions`, and routes I²C reads/writes to fake
  devices that tests register with `machine.register_device(addr, dev)`.
- `neopixel.py` — fake `NeoPixel`. Records every `write()` so tests can
  assert what colour the firmware would have shown.
- `ujson.py` — re-exports CPython's `json`.
- `ustruct.py` — re-exports CPython's `struct`.
- `utime.py` — `sleep_ms` is a no-op (tests don't wait); `ticks_ms` /
  `ticks_diff` are backed by `time.monotonic`.
- `micropython.py` — `const(x)` returns `x` unchanged.

Tests reset the recorded state between cases by calling
`machine.reset()` (and `NeoPixel.instances.clear()` where relevant)
from an autouse fixture.

## Notes
The package is a uv workspace member. The `pytest` Docker stage runs
`uv sync`, which installs these six modules into the test venv as
top-level imports. There's exactly one copy on the host, so every
package's tests see the same `machine` module — no per-package stub
directories, no `sys.path` tricks. Never copied to the device.

**Adding a new shim:**
1. Extend the relevant `micropython_stubs/<module>.py` (or add a new file).
2. Add the new file to the `force-include` table in `pyproject.toml`.
3. Re-run the tests:
   ```
   docker compose run --rm --build test
   ```

## Tests
Shims are exercised by every other package's host pytest suite. Behaviour regressions surface there.
