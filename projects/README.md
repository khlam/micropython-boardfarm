# projects

Self-contained boardfarm projects: chip-agnostic firmware, a per-project
static dashboard, per-project tests, and the project's own
`docker-compose.yaml`. The Dockerfiles ([Dockerfile.firmware](../Dockerfile.firmware), [Dockerfile.host](../Dockerfile.host) for the dashboard) are shared.

Run project commands from inside a project directory.

## Project Layout
```
<project>/
  firmware/main.py            chip-agnostic entry point — no `if _IS_ESP32` branches
  viz/static/index.html       per-project dashboard (HTML/JS, served by
                              the shared serial_over_web FastAPI server)
  tests/                      host pytest for the project's emit() schema
  outputs/                    build artifacts (app.rp2040.rp2350.uf2, app.esp32-s3.bin)
  docker-compose.yaml         pi-compile / esp32-compile / esp32-flash / viz services
  README.md                   compile, flash, dashboard, wiring
```

## Projects

| Project | Sensor | Stream rate | Dashboard |
|---|---|---|---|
| [distance-stream](distance-stream/) | VL53L0X ToF | ~50 Hz | Plotly line chart of `distance_mm` |
| [gyro-stream](gyro-stream/) | MPU6050 IMU (accel + gyro + temp) | ~100 Hz | Plotly multi-trace + 3D orientation view |
| [multizone-ranging](multizone-ranging/) | VL53L5CX 8×8 ToF | ~15 Hz | Plotly 8×8 3D point cloud + distance stats |

## Usage
From `projects/<project>/`:

| Task | Command |
|---|---|
| Compile firmware (RP2040 + RP2350 → single universal UF2) | `docker compose up --build pi-compile` |
| Compile ESP32-S3 firmware (no board needed) | `docker compose up --build esp32-compile` |
| Compile + flash ESP32-S3 (board must be in bootloader mode) | `docker compose run --rm --build esp32-flash` |
| Run dashboard at http://localhost:18501 | `docker compose up --build viz` |

Per-board flash and bootloader-mode steps: [microcontrollers.md](microcontrollers.md).

Tests run from the **repo root** (one consolidated service for every project, package, and the dashboard):
```
docker compose up pytest --build --exit-code-from pytest             # everything
docker compose run --rm pytest /projects/distance-stream/tests       # one project
docker compose run --rm pytest /firmware-packages/vl53l0x/tests -k status   # path + filter
```

The `/projects/...` path is a bind-mount inside the container (mapped from the host's `./projects` by the root [docker-compose.yaml](../docker-compose.yaml) at runtime, read-only). Project firmware isn't `COPY`'d into the image, so edits take effect without rebuilding.

## Notes
- **Firmware stays MCU-agnostic.** `main.py` works identically on every
  MCU the project supports. MCU-specific behaviour belongs in a shared
  package backend — see [`../firmware-packages/README.md`](../firmware-packages/README.md).
- **All serial output goes through `emit()`.** One `ujson.dumps` per line.
  Raw `print()` pollutes the JSON stream and is silently dropped by the
  viz parser. The per-project `tests/test_emit_schema.py` enforces this.
- **The viz dashboard is per-project; the server is shared.** Every
  project's `viz/` contains only `static/` — the FastAPI server lives in
  [`../cpython-packages/serial_over_web/`](../cpython-packages/serial_over_web/) and is mounted
  into the image at build time.
- **Adding a new project:** copy an existing project directory, then edit
`firmware/main.py`, `viz/static/index.html`, `tests/test_emit_schema.py`,
and the `VIZ_DIR` build-arg in `docker-compose.yaml`. The Dockerfiles,
[`firmware-packages/`](../firmware-packages/), and [`cpython-packages/serial_over_web/`](../cpython-packages/serial_over_web/) all stay unchanged.
