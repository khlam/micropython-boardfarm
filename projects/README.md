# projects

Self-contained boardfarm projects: chip-agnostic firmware, a per-project
static dashboard, per-project tests, and the project's own
`docker-compose.yaml`. The Dockerfiles ([Dockerfile.firmware](../Dockerfile.firmware) for compiling, [Dockerfile.host](../Dockerfile.host) for the `uv` lock runner) are shared.

Run project commands from inside a project directory.

## Project Layout
```
<project>/
  firmware/main.py            chip-agnostic entry point — no `if _IS_ESP32` branches
  viz/static/index.html       per-project dashboard (HTML/JS); open it in
                              Chrome/Edge — it reads the board via Web Serial
  tests/                      host pytest for the project's emit() schema
  outputs/                    build artifacts (app.rp2040.rp2350.uf2, app.esp32-s3.bin)
  docker-compose.yaml         pi-compile / esp32-compile / esp32-flash services
  README.md                   compile, flash, dashboard, wiring
```

## Projects

| Project | Sensor | Stream rate | Dashboard |
|---|---|---|---|
| [distance-stream](distance-stream/) | VL53L0X ToF | ~50 Hz | Plotly line chart of `distance_mm` |
| [gyro-stream](gyro-stream/) | MPU6050 IMU (accel + gyro + temp) | ~100 Hz | Plotly multi-trace + 3D orientation view |

## Usage
From `projects/<project>/`:

| Task | Command |
|---|---|
| Compile firmware (RP2040 + RP2350 → single universal UF2) | `docker compose up --build pi-compile` |
| Compile ESP32-S3 firmware (no board needed) | `docker compose up --build esp32-compile` |
| Compile + flash ESP32-S3 (board must be in bootloader mode) | `docker compose run --rm --build esp32-flash` |
| Open the dashboard | open `viz/static/index.html` in Chrome or Edge, then click **Connect** |

Tests run from the **repo root** (one consolidated service for every project and package):
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
- **The viz dashboard is per-project and runs entirely in the browser.**
  Every project's `viz/` contains only `static/index.html`; opened in
  Chrome or Edge it reads the board directly over the Web Serial API, so
  there is no host-side server to run.
- **Adding a new project:** copy an existing project directory, then edit
`firmware/main.py`, `viz/static/index.html`, and `tests/test_emit_schema.py`.
The Dockerfiles and [`firmware-packages/`](../firmware-packages/) all stay
unchanged.
