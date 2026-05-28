# AGENTS.md — Generic MicroPython

## Host policy (read first)
**Never install anything on the host machine.** Docker is the only required host tool. All toolchains, flashers, serial readers, tests, and helper scripts run inside Docker — invoke them via the project's `docker compose` services. If a workflow seems to require a host install (pip, brew, apt, pipx, esptool, MicroPython, etc.), wrap it in a Docker stage instead.

## Terminology
- **MCU** — MicroPython on the chip. Code lives in `projects/<project>/firmware/` and `firmware-packages/<pkg>/<pkg>/`.
- **host** — CPython in Docker. Runs the dashboard, compile toolchains, and pytest. [micropython_stubs](cpython-packages/micropython_stubs/) lets pytest exercise MCU code on the host.

## Design
This is a shared-projects monorepo. Projects (`projects/<project>/`) contain general, chip-agnostic firmware that compiles for all chips the project supports. Chip-specific behavior belongs exclusively in package backends (`firmware-packages/`), following the pattern established by `boot_status_led`.

`<project>` denotes any subdirectory under `projects/` — list it with `ls projects/` to see what's currently present, and substitute the real name when running commands.

## Start here (routing)
Before changing anything, identify the area you're touching:
- **Projects directory** — `projects/<project>/firmware/main.py`
- **Shared packages (chip backends, driver)** — `firmware-packages/boot_status_led/` and `firmware-packages/vl53l0x/`
- **Viz/dashboard** — `projects/<project>/viz/`
- **Compile system** — `Dockerfile.firmware`, `Dockerfile.tests`, `Dockerfile.host` (viz + uv-runner) + `projects/<project>/docker-compose.yaml`

When unsure, use **Key references** at the bottom.

---

## Change workflow (follow in order)
1. Identify the chip(s) affected (RP2040, RP2350, ESP32-S3, or all three).
2. If the change requires chip-specific behavior, add or update a package backend — do not branch inside project firmware.
3. Make the smallest change that achieves the goal — don't add shared abstractions for a single chip.
4. Compile firmware before reporting done.
5. If the JSON schema changes, update the viz `app.py` parser and `index.html` display logic in the same change.

---

## Commands (copy/paste, run from `projects/<project>/`)

### Compile firmware
```
docker compose up --build pi-compile         # RP2040 + RP2350 → ./outputs/app.rp2040.rp2350.uf2
docker compose up --build esp32-compile      # ESP32-S3 → ./outputs/app.esp32-s3.bin
docker compose up --build --exit-code-from esp32-flash esp32-flash  # ESP32-S3 → compile, then flash
```

### Run dashboard
```
docker compose up --build viz          # → http://localhost:18501
```

### Clean compile caches (this project only)
```
docker compose down -v                 # drops build-cache
```

Pass `--build` whenever firmware or package files change — images copy files at build time, not via volume mount.

### Run tests (from the repo root, not a project dir)
```
docker compose up pytest --build --exit-code-from pytest            # everything
docker compose run --rm pytest /projects/distance-stream/tests      # one project
docker compose run --rm pytest /firmware-packages/vl53l0x/tests              # one package
docker compose run --rm pytest /firmware-packages/mpu6050/tests -k who_am_i  # filter
```
Tests live in one consolidated service at the repo root (`docker-compose.yaml`), not per-project. Any positional args override the default target set (`/firmware-packages /projects /cpython-packages/serial_over_web/tests`) — no implicit merging. The `up … --exit-code-from pytest` form is required so a failing test makes the command exit non-zero; plain `up` silently swallows the failure.

### Python deps / locks (from the repo root)
- `docker compose run --rm uv lock` (when editing `pyproject.toml` / `uv.lock`)

---

## Architecture & invariants

### Project firmware is chip-agnostic (critical)
- Project `main.py` must work identically on all chips the project supports — no `if _IS_ESP32`, no `os.uname()` checks, no chip-specific I²C or GPIO choices in project code.
- Chip-specific behavior is encapsulated in package backends and selected at import time (see LED state machine dispatch and ToF driver `skip_spad_info` as examples of the pattern).
- Adding a new supported chip means adding a package backend, not branching in `main.py`.

### JSON output schema (invariant)
- All output goes through `emit()` — one `ujson.dumps` per line. Raw `print()` outside `emit()` pollutes the serial stream and is silently dropped by the viz parser.
- `distance_mm` is `null` when `tof.read() >= 8190` (out-of-range), an integer mm otherwise.

### Packages are frozen for firmware, installed editable for tests
- For firmware: each package's `<pkg>/` directory under `firmware-packages/<pkg>/` is frozen into `ports/rp2/modules/<pkg>/` (RP) or `ports/esp32/modules/<pkg>/` (ESP32) at build time via `manifest.py`'s `package()` call. MicroPython's module resolution picks them up automatically. `tests/`, `pyproject.toml`, and `README.md` under each package are not copied to the device.
- For host tests: each package is a uv workspace member (declared in the root [pyproject.toml](pyproject.toml)). The `pytest` stage in [Dockerfile.tests](Dockerfile.tests) `uv sync`s every member into `/work/.venv` editable, so `import mpu6050` etc. resolve normally — no per-package `sys.path` mutation.

### Package layout
- `firmware-packages/<pkg>/pyproject.toml` — minimal hatchling metadata that makes the package a uv workspace member. Not seen by `manifest.py` (firmware freeze finds `<pkg>/<pkg>/` directly).
- `firmware-packages/<pkg>/<pkg>/` — firmware modules (`__init__.py` + submodules). Pylance resolves `import <pkg>` via `python.analysis.extraPaths` in [.vscode/settings.json](.vscode/settings.json) pointing at each package's root. Only the inner `<pkg>/` directory ships to the chip; sibling `tests/`, `pyproject.toml`, `README.md` are filtered out by `manifest.py`'s `package()` call.
- `firmware-packages/<pkg>/tests/` — host pytest. `tests/conftest.py` contains only fixtures; no `sys.path`/`sys.modules` mutation. Sibling helper files (e.g. `fake_mpu6050.py`) are reachable because the root [pyproject.toml](pyproject.toml)'s `[tool.pytest.ini_options] pythonpath` adds each package's `tests/` to the import path.
- `firmware-packages/<pkg>/README.md` — usage, public API, chip-dispatch rationale.

### Shared host-test stubs
- `cpython-packages/micropython_stubs/micropython_stubs/` holds **one** copy each of `machine.py`, `neopixel.py`, `micropython.py`, `ustruct.py`, `utime.py`, `ujson.py`. The wheel re-promotes them to top-level via hatch `force-include`, so every host test resolves `import machine` etc. against the same module — no per-package stub directories, no cross-package contamination.
- The `machine` stub keeps a single module-level `_devices: dict` and `pin_constructions: list`. Tests reset state via `machine.reset()` (and `neopixel.reset()` where relevant) in an autouse fixture.
- If a new test needs behavior not in the shared stub, add it to `cpython-packages/micropython_stubs/micropython_stubs/<module>.py` and list the new file in the `force-include` table of `pyproject.toml`. Never bring back per-package `stubs/`.

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
- No shell scripts at the repo root; dispatch logic lives inside each Docker stage's `ENTRYPOINT` (heredoc for the firmware compile stages in `Dockerfile.firmware`, plain exec form for `pytest` in `Dockerfile.tests`).
- Don't add host dependencies outside Docker — Docker is the only required host tool.
- Avoid destructive git operations and unrelated reversions.
- Never edit `firmware-packages/vl53l0x/vl53l0x/vl53l0x.py` — it is vendored (with local modifications for the ESP32-S3 breakout wrapper) from [github.com/uceeatz/VL53L0X](https://github.com/uceeatz/VL53L0X). See [firmware-packages/vl53l0x/VENDOR.md](firmware-packages/vl53l0x/VENDOR.md) for the source commit and divergence notes.

---

## Common pitfalls
- **Putting chip-specific branches in project firmware** — `if _IS_ESP32` / `os.uname()` checks in `main.py` violate the shared-projects design. Move chip detection into a package backend instead (see `firmware-packages/boot_status_led/boot_status_led/status.py` for the dispatch pattern).
- **Printing outside `emit()`** — output appears in the serial stream and confuses the viz JSON parser.
- **Editing any Dockerfile to add a new project** — wrong. Copy an existing `projects/<project>/`, edit `main.py` and the `VIZ_DIR` build-arg in the new `docker-compose.yaml`. The Dockerfiles are unchanged.
- **Running `esp32-flash` without the board in bootloader mode** — the ENTRYPOINT fails fast on missing `/dev/ttyACM0`; put the board in bootloader mode first.
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
| Firmware compile | `Dockerfile.firmware` | Stages: `rp`, `esp32-compile`, `esp32-flash` |
| Host tests | `Dockerfile.tests` | Stage: `pytest` |
| Host runtime | `Dockerfile.host` | Stages: `viz`, `uv-runner` |
| Project compose | `projects/<project>/docker-compose.yaml` | `build.context: ../..` → repo root |
| RP firmware output | `projects/<project>/outputs/app.rp2040.rp2350.uf2` | Universal UF2 for RP2040 + RP2350 |
| ESP32 firmware output | `projects/<project>/outputs/app.esp32-s3.bin` | ESP-IDF `.bin`; `esp32-compile` compiles, `esp32-flash` flashes |
