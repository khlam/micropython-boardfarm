# tools

## Matter build tooling — `tools/matter-build/`

- `build.py` — the whole `esp32-compile` run: board-config parsing, compile, credential minting, merge, artifact validation, publish; it also gzips the project's `viz/static/index.html` into a generated `dashboard_page` module and hands manifest.py the staging directory as `FROZEN_STAGING_DIR`, so the board serves the same page the host viz service does.
- `spake2p.py` — SPAKE2+ verifier via `cryptography` (no `ecdsa`).
- `onboarding_codes.py` — QR/manual pairing-code encoding, the mirror of `build.py`'s own decoders.
- `nvs_partition_gen.py` — writes the `chip-factory` NVS partition via the `esp-idf-nvs-partition-gen` package.
- `nvs_partition_read.py` — reads it back via ESP-IDF's `nvs_tool.py` for validation.
- `qr_image.py` — QR PNG rendering via `qrcode[pil]`.
- `serial_monitor.py` — bounded serial capture.
- `tests/` — host pytest coverage of the parsers, pairing-code decoders, and the structural factory-identity check (verifier/salt present, no plaintext passcode — not a cryptographic proof).

Bind-mounted to `/matter-tools` for the build and `/tools` for pytest, never installed.
