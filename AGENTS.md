# AGENTS.md

## Host policy
**Never install anything on the host machine.** Docker is the only required host tool. All toolchains, flashers, serial readers, tests, and helper scripts run inside Docker — invoke them via the project's `docker compose` services. If a workflow seems to require a host install (pip, brew, apt, pipx, esptool, MicroPython, etc.), wrap it in a Docker stage instead.

## Terminology
- **MCU** — MicroPython on the chip. Code lives in `projects/<project>/firmware/` and `firmware-packages/<pkg>/<pkg>/`.
- **host** — CPython in Docker. Runs the dashboard, build toolchains, and pytest. [micropython_stubs](cpython-packages/micropython_stubs/) lets pytest exercise MCU code on the host.

## Design
This is a shared-projects monorepo. Projects (`projects/<project>/`) contain general, chip-agnostic firmware that builds for all chips the project supports. Chip-specific behavior belongs exclusively in package backends (`firmware-packages/`), following the pattern established by `boot_status_led`. Project `main.py` files must not contain chip-detection branches.

`<project>` denotes any subdirectory under `projects/` — list it with `ls projects/` to see what's currently present, and substitute the real name when running commands.

## Routing
Before changing anything, identify the area you're touching:
- **Projects directory** — `projects/<project>/firmware/main.py`
- **Shared packages (chip backends, driver)** — `firmware-packages/boot_status_led/` and `firmware-packages/vl53l0x/`
- **Viz/dashboard** — `projects/<project>/viz/`
- **Build system** — `Dockerfile.firmware`, `Dockerfile.tests`, `Dockerfile.host` (viz + uv-runner) + `projects/<project>/docker-compose.yaml`

When unsure, use **Key references** at the bottom.

## Workflow (follow in order)
1. Identify the chip(s) affected (RP2040, RP2350, ESP32-S3, or all three).
2. If the change requires chip-specific behavior, add or update a package backend — do not branch inside project firmware.
3. Make the smallest change that achieves the goal — don't add shared abstractions for a single chip.
4. Build firmware and confirm it compiles before reporting done.


## Commands (copy/paste, run from `projects/<project>/`)

### Build firmware
```
docker compose up --build compile      # RP2040 + RP2350 → ./outputs/app.rp2040.rp2350.uf2
docker compose run --rm --build esp32  # ESP32-S3 → builds + flashes $SERIAL_PORT (default /dev/ttyACM0)
```

### Clean build caches (this project only)
```
docker compose down -v                 # drops build-cache
```

### Run tests
```
docker compose up pytest --build --exit-code-from pytest                                     # everything
docker compose up pytest --build --exit-code-from pytest -- /projects/distance-stream/tests  # one project
docker compose up pytest --build --exit-code-from pytest -- /firmware-packages/vl53l0x/tests # one package
```

### Python deps / locks (from the repo root)
```
docker compose run --rm uv lock
```

---

## Architecture & invariants

### JSON output schema
- Use `emit()` for all output. Raw `print()` breaks the viz parser silently.

### Packages are frozen for firmware, installed editable for tests
- Firmware: `manifest.py` copies only `firmware-packages/<pkg>/<pkg>/` onto the chip. `tests/`, `pyproject.toml`, and `README.md` are excluded.
- Tests: `uv sync` installs every package editable into `/work/.venv`, so imports resolve inside the `pytest` Docker service. Do not add `sys.path` mutations.

### Package layout
- `firmware-packages/<pkg>/pyproject.toml` — makes this a uv workspace member so tests can import it. Ignored by firmware builds.
- `firmware-packages/<pkg>/<pkg>/` — the actual package. Only this inner directory ships to the chip; `tests/`, `pyproject.toml`, and `README.md` are excluded.
- `firmware-packages/<pkg>/tests/` — host tests. Put fixtures in `conftest.py`; sibling helpers (e.g. `fake_mpu6050.py`) are importable without `sys.path` hacks.
- `firmware-packages/<pkg>/README.md` — usage, public API, chip-dispatch rationale.

### Shared host-test stubs
- All MicroPython stubs live in `cpython-packages/micropython_stubs/micropython_stubs/`
- Reset `machine` and `neopixel` state with `machine.reset()` / `neopixel.reset()` in an autouse fixture.
- To extend a stub, edit the file there and add it to `force-include` in `pyproject.toml`.

### Universal UF2 vs ESP32 bin (invariant)
- `outputs/app.rp2040.rp2350.uf2` covers RP2040 and RP2350 only — each bootloader skips foreign-family blocks.
- `outputs/app.esp32-s3.bin` is a separate ESP-IDF image flashed via `esptool.py`. **Never concatenate them.**

---

## Docstrings & function documentation
All Python code follows the [Google Python Style Guide](https://google.github.io/styleguide/pyguide.html), enforced by ruff (see [pyproject.toml](pyproject.toml)) — no exceptions for firmware, drivers, tools, or tests. Every module, class, and function gets a docstring — no exceptions, including small helpers, chip backends, and one-line utilities. Use Google-style: a one-line summary, blank line, then `Args:` / `Returns:` / `Raises:` sections when they add information. State the *why* and any non-obvious invariants — restating the signature in prose is noise. Tests are the only exception; `D100`/`D103` are ignored under `**/tests/*` in [pyproject.toml](pyproject.toml).

**Don't preserve the past — in prose or in code.** No "replaces …" / "previously …" phrasing in comments; no dead branches, compat shims, or aliases for renamed symbols. Git covers history. Exception: when prior state explains a current workaround or silicon/library quirk that would otherwise look arbitrary.

## File layout
Standard Python ordering, no exceptions (firmware, drivers, tools, tests): module docstring → `import` statements → module-level constants → public API (exported functions/classes; tests in test files) → private helpers (`_`-prefixed functions/classes; pytest fixtures).

## Code style & runtime conventions
- MicroPython on RP2040: 264 KB SRAM, no threads, no pip. Use `const()` for register addresses; pre-allocate buffers in tight loops.
- Never spin without `sleep` (≥ 10 ms) — starves the MicroPython scheduler.
- Wrap `sensor.read()` in `try/except` — sensors occasionally NACK. On exception, call `status.read_err()` and `continue` the loop; never let a stray exception crash the loop.
- `main.py` calls only named `status.*()` transitions — no raw RGB tuples in streaming logic.
- Chip-specific logic belongs in packages, not in project firmware. Each package keeps MCU code under `firmware-packages/<pkg>/<pkg>/` (flat `.py` + `__init__.py`) and declares a `pyproject.toml` at `firmware-packages/<pkg>/` so uv can install it editable for host tests. Host tests live under `firmware-packages/<pkg>/tests/`. Use the backend-dispatch pattern (`os.uname().machine` at import time) that `boot_status_led` already establishes.
- Don't install tools on the host. All toolchains (esptool, ARM cross-compiler, ESP-IDF, uv, MicroPython source) live inside Docker images.
- Don't add dependencies without tests + `uv lock`.

---

## Safety & repo boundaries
- Never read or write `projects/*/outputs/` files directly — they are build artifacts.
- No shell scripts at the repo root; dispatch logic lives inside each Docker stage's `ENTRYPOINT` (heredoc for the firmware-build stages in `Dockerfile.firmware`, plain exec form for `pytest` in `Dockerfile.tests`).
- Don't add host dependencies outside Docker — Docker is the only required host tool.
- Avoid destructive git operations and unrelated reversions.
- Never edit `firmware-packages/vl53l0x/vl53l0x/vl53l0x.py` — it is vendored (with local modifications for the ESP32-S3 breakout wrapper) from [github.com/uceeatz/VL53L0X](https://github.com/uceeatz/VL53L0X). See [firmware-packages/vl53l0x/VENDOR.md](firmware-packages/vl53l0x/VENDOR.md) for the source commit and divergence notes.

---

## Common pitfalls
- **Putting chip-specific branches in project firmware** — `if _IS_ESP32` / `os.uname()` checks in `main.py` violate the shared-projects design. Move chip detection into a package backend instead (see `firmware-packages/boot_status_led/boot_status_led/status.py` for the dispatch pattern).
- **Printing outside `emit()`** — output appears in the serial stream and confuses the viz JSON parser.
- **Editing any Dockerfile to add a new project** — wrong. Copy an existing `projects/<project>/`, edit `main.py` and the `VIZ_DIR` build-arg in the new `docker-compose.yaml`. The Dockerfiles are unchanged.
- **Running `esp32` service without the board in bootloader mode** — the ENTRYPOINT fails fast on missing `/dev/ttyACM0`; put the board in bootloader mode first.
- **Forgetting `--build` after editing files** — Docker images copy files at build time; without `--build` the container runs stale firmware.

---

## Key references (keyword → file)

| Keyword | File | Notes |
| --- | --- | --- |
| Entry point | `projects/<project>/firmware/main.py` | I²C scan, sensor init, JSON streaming loop |
| LED state machine | `firmware-packages/boot_status_led/boot_status_led/status.py` | Named transitions + colour constants, chip dispatch |
| ToF driver | `firmware-packages/vl53l0x/vl53l0x/vl53l0x.py` | `VL53L0X(i2c, skip_spad_info=False, interrupt_status_mask=0x07)` |
| Viz backend | `projects/<project>/viz/app.py` | Serial reader + WebSocket broadcaster on `/ws` |
| Viz dashboard | `projects/<project>/viz/static/index.html` | Plotly line chart + numeric readout |
| Firmware build | `Dockerfile.firmware` | Stages: `rp`, `esp32` |
| Host tests | `Dockerfile.tests` | Stage: `pytest` |
| Host runtime | `Dockerfile.host` | Stages: `viz`, `uv-runner` |
| Project compose | `projects/<project>/docker-compose.yaml` | `build.context: ../..` → repo root |
| RP firmware output | `projects/<project>/outputs/app.rp2040.rp2350.uf2` | Universal UF2 for RP2040 + RP2350 |
| ESP32 firmware output | `projects/<project>/outputs/app.esp32-s3.bin` | ESP-IDF `.bin`, flashed by `esp32` service |
