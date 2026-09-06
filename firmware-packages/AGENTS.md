# firmware-packages

## Design

Chip-specific *behavior* (driver implementations, hardware abstraction) belongs in package backends (`firmware-packages/`), following the pattern established by `boot_status_led`. Each package keeps MCU code under `firmware-packages/<pkg>/<pkg>/` (flat `.py` + `__init__.py`). Host tests live under `firmware-packages/<pkg>/tests/`. Use the backend-dispatch pattern (`os.uname().machine` at import time) that `boot_status_led` already establishes.

Each driver constructor takes those pins as flat keyword arguments (hardware I²C: `sda=`/`scl=`/`bus_id=`; bit-banged soft I²C: `sda=`/`scl=` only; UART: `bus_id=`/`tx=`/`rx=`; SPI: `spi_id=`/`sck=`/`mosi=`/`cs=`), opens whatever bus it needs internally via the `i2c_bus` utility (projects never see a bus object), and scans — raising a specific `DeviceNotFoundError` (not a bare `OSError`) when the expected device is absent, so the project's retry loop can tell "nothing on the bus" from "init failed". A driver re-exports `DeviceNotFoundError` so the project imports its retry-loop exception from the driver, never from `i2c_bus`. Use `DeviceNotFoundError` when expected hardware is absent. Use `OSError` or a more specific exception for genuine I/O failures.

Packages receive pins as arguments from the caller; they never claim pins at import time.

## Routing

Before changing anything, identify the area you're touching:

| Area | Path | Key files |
| --- | --- | --- |
| LED state machine | `firmware-packages/boot_status_led/boot_status_led/` | `status.py` — named transitions + colour constants, chip dispatch |
| I²C bus (internal) | `firmware-packages/i2c_bus/i2c_bus/` | `__init__.py` — `soft_i2c(sda, scl)` / `hard_i2c(bus_id, sda, scl)` + `DeviceNotFoundError`; consumed only by drivers, never by projects |
| ToF driver | `firmware-packages/vl53l0x/vl53l0x/` | `vl53l0x.py` — `VL53L0X(sda=, scl=, skip_spad_info=True, interrupt_status_mask=0xFF)`; opens its own soft I²C, scans → `DeviceNotFoundError` |
| IMU driver | `firmware-packages/mpu6050/mpu6050/` | `mpu6050.py` — `MPU6050(sda=, scl=, bus_id=0)`; opens its own hard I²C, auto-detects 0x68/0x69 → `DeviceNotFoundError` |
| Radar drivers | `firmware-packages/radar/radar/`, `projects/ld2450/` | `__init__.py` — the `Model` string-constant vocabulary, the ordered `DRIVERS` registry, `driver(model, bus_id=, tx=, rx=)` for a known radar, and `detect(bus_id=, tx=, rx=)` for probe-and-discover (→ `NoRadarError`); `stream.py` — `ReportStream`, the IRQ-driven reader every driver subclasses (framing, resync, newest-report selection, `wait_ready`/`read_latest`/`close`) plus `DeviceNotFoundError` and the one shared `Target`; `ld2450.py` — three-slot decoder, read-only; `ld2420.py` — same, but `_prepare()` commands energy mode at startup and it measures range only, so it fills `y_mm` and leaves the other fields zero. Each radar is a submodule; callers switch on `Model`, never on a package name |
| On-device web server | `firmware-packages/httpd/httpd/` | `server.py` — `Server(port=)`, `.page()` for a fixed body, `.stream()` for a WebSocket fan-out; `websocket.py` — RFC 6455 handshake/framing plus `Broadcast.send()`, which never raises or blocks. Serves bodies decided before start; parses nothing it forwards |
| Matter interface | `firmware-packages/matter/` | `matter/schema.py` — attribute vocabulary + validation rules, nothing native; `matter/endpoint.py` — `Endpoint` and the named attribute accessors (`.on`/`.level`/`.hue`/…); `matter/node.py` — `Node` lifecycle and snapshot polling; `matter/__init__.py` — re-export only; `native/` — ESP-Matter `_matter` bridge; `ARCHITECTURE.md` — mermaid call-path diagrams across the native boundary |

## Packages are frozen for firmware †

`manifest.py` copies only `firmware-packages/<pkg>/<pkg>/` onto the chip — `tests/`, `pyproject.toml`, and `README.md` are excluded.

## ESP-Matter boundary †

`firmware-packages/matter` exists exclusively to connect MicroPython applications to ESP-Matter. Native ESP-Matter owns endpoint schemas, secure sessions, BLE/Wi-Fi commissioning, fabrics, persistence, controller commands, and attribute transport. The public MicroPython interface owns attribute validation, endpoint mirrors, callback routing, local publication, and administration calls.

Projects own product state derived from that interface, board mappings, color conversion, brightness decisions, GPIO/NeoPixel access, and hardware lifecycle. Do not put a product-specific runtime, color renderer, fixed pin, or hardware helper in the `matter` package or its native bridge. CHIP tasks retain coalesced state natively; Python pulls it by calling `Node.poll()` on the VM task and never runs on a CHIP task or interrupt.

## Vendored and generated code

Do not mechanically restyle vendored code.

Keep vendor modifications minimal and update `VENDOR.md` where present.

Do not hand-edit or reformat generated firmware/configuration blobs.

---

† Project-specific quirk — e.g. behavior that differs between the MicroPython firmware runtime and the CPython host-test environment.
