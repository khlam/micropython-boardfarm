# vl53l0x vendoring

`vl53l0x/vl53l0x.py` originates from the community MicroPython port at
[github.com/uceeatz/VL53L0X](https://github.com/uceeatz/VL53L0X).

| Field | Value |
| --- | --- |
| Upstream | https://github.com/uceeatz/VL53L0X |
| File | `VL53L0X.py` |
| Source commit | `975d212a33f67b4f41ae64a2bc3b65f62845e852` |
| Source commit date | 2019-03-20 |
| Last sync | 2026-05-22 |

Upstream has had no further commits touching `VL53L0X.py` since the source
commit above; `master` HEAD (`f73a9798`) is a README-only change.

## Divergence from upstream

The local copy is **not byte-for-byte verbatim**. Observed differences vs.
upstream `975d212a`:

- Import order rearranged; `from machine import Timer` and `import time`
  dropped (unused).
- Register-address literals normalised to upper-case hex (e.g. `0x4F` vs.
  upstream `0x4f`).
- Driver body extended (~689 lines locally vs. 522 upstream) to support
  the wrapper surface described in [README.md](README.md) —
  `skip_spad_info` and `interrupt_status_mask` constructor options for
  the ESP32-S3 breakout.
- Project-specific concerns — soft I²C bus creation, device scan,
  `DeviceNotFoundError`, soft-reset, and default overrides — live in
  ``__init__.py`` as a thin subclass. The vendored file takes a pre-built
  ``i2c`` object and has no dependency on ``i2c_bus``.

Treat the file as a vendored-with-local-modifications snapshot: don't
re-sync from upstream without re-applying these changes, and don't edit
it for unrelated reasons (see the no-edit rule in
[../AGENTS.md](../AGENTS.md)).
