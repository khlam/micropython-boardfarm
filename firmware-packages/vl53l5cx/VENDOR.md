# vl53l5cx vendoring

`vl53l5cx/vl53l5cx.py` and `vl53l5cx/_config_bytes.py` originate from the
MicroPython port at [github.com/mp-extras/vl53l5cx](https://github.com/mp-extras/vl53l5cx).

| Field | Value |
| --- | --- |
| Upstream | https://github.com/mp-extras/vl53l5cx |
| Files | `vl53l5cx/__init__.py`, `vl53l5cx/mp.py`, `vl53l5cx/_config_bytes.py` |
| Source commit | `c7476877e96fabe81516176fbe8c575923d368b1` |
| Source commit date | 2021-10-07 |
| Last sync | 2026-05-28 |
| License | MIT |

## Divergence from upstream

The local copies are **not byte-for-byte verbatim**. Observed differences:

- `vl53l5cx/__init__.py` (base class) and `vl53l5cx/mp.py` (MicroPython I²C
  adapter) have been merged into a single `vl53l5cx/vl53l5cx.py` module.
- The upstream two-class hierarchy (`VL53L5CX` base + `VL53L5CXMP` subclass)
  is collapsed into a single `VL53L5CX` class.
- ConfigData source switched from the file-based `_config_file.py` (reads
  `vl_fw_config.bin` at runtime) to `_config_bytes.py` (firmware frozen into
  device flash as Python bytes). This makes the package self-contained on
  MicroPython without filesystem access.
- Google-style docstrings added to all methods per `AGENTS.md`.
- Three convenience methods added for project firmware use: `start(freq)`,
  `read()`, and `stop()`.
- `_config_bytes.py` is copied verbatim; see it for the MIT copyright notice.
- `cp.py` and `_config_file.py` are not included (CircuitPython adapter and
  file-based firmware loader are not needed in this repo).

Treat `vl53l5cx.py` and `_config_bytes.py` as vendored-with-local-modifications
snapshots: don't re-sync from upstream without re-applying these changes.
