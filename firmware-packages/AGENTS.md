# micropython firmware-packages

## Design

Code belongs in `firmware-packages` when the functionality is the same but the implementation differs by hardware. The hardware-specific half lives in a per-chip backend module inside the package. `firmware-packages` code is pure and general and should not contain project-specific code. `firmware-packages` receives hardware-specific arguments such as pins from the caller.

Each package keeps MCU code under `firmware-packages/<pkg>/<pkg>/` (flat `.py` + `__init__.py`). Host tests live under `firmware-packages/<pkg>/tests/`.

Callers dispatch to the backend once at import time on os.uname().machine, binding the chip's implementation to a private name the rest of the module calls:

```
import os

_machine = os.uname().machine
if "ESP32S3" in _machine:
    from <pkg>.esp32s3 import show as _show
elif "RP2350" in _machine:
    from <pkg>.rp2350 import show as _show
else:
    from <pkg>.rp2040 import show as _show
```

## Find the package

- **What it does** — the Packages table in [README.md](README.md), then the package's own `README.md`.
- **Public API** — `<pkg>/<pkg>/__init__.py`: its `__all__` and module docstring are the contract. The register-level or vendored module beneath it is not; a wrapper there may narrow or re-default the signature the vendored file exposes.
- **How it is wired to a board** — the calling project's `main.py` and its `BOARD` pin table, never a pin fixed in the package.

## Cross-package contracts

Rules no single package's README states, because they constrain its callers:

- `i2c_bus` is consumed only by drivers, never by projects.
- `httpd` serves bodies decided before start; parses nothing it forwards. `Broadcast.send()` never raises or blocks.
- `matter/` splits at the native boundary: `matter/` is the MicroPython interface, `native/` the ESP-Matter `_matter` bridge. [matter/ARCHITECTURE.md](matter/ARCHITECTURE.md) has the mermaid call-path diagrams across it.

## Packages are frozen for firmware †

`manifest.py` copies only `firmware-packages/<pkg>/<pkg>/` onto the chip — `tests/`, `pyproject.toml`, and `README.md` are excluded.

## ESP-Matter boundary †

All application logic belongs in MicroPython. `firmware-packages/matter` is a wrapper around ESP-Matter for MicroPython applications to safely call. Treat native C ESP-Matter as vendored; it owns the protocol and the security, do not reimplement it.  MicroPython reaches native state only through `Node.poll()` on the VM task, never on a CHIP task or interrupt.

## Vendored and generated code

Do not restyle vendored code.

Keep vendor modifications minimal and update `VENDOR.md` where present.

Do not hand-edit or reformat generated firmware/configuration blobs.

---

† Project-specific quirk — e.g. behavior that differs between the MicroPython firmware runtime and the CPython host-test environment.
