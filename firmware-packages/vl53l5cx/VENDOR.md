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
- `_config_bytes.py` retains the upstream MIT copyright notice and byte
  payloads verbatim, but its `fw_data()` generator was rewritten to slice the
  frozen `bytes` directly instead of wrapping them in `io.BytesIO` (the stream
  object and its context-manager protocol are not present on every MicroPython
  port). Module/class/method docstrings were added per `AGENTS.md`.
- `cp.py` and `_config_file.py` are not included (CircuitPython adapter and
  file-based firmware loader are not needed in this repo).

### Local correctness fixes and cleanup

Applied on top of the vendored snapshot; re-apply if re-syncing:

- `stop_ranging()`: `struct.unpack("<I", buf)` returns a tuple, so the upstream
  `auto_stop_flag != 0x4FF` guard was always true. Indexed `[0]` so the flag is
  compared as an integer.
- `integration_time_ms` setter: dropped a dead `self._b1[0] = itime` write. It was
  unused (the real write uses `struct.pack`) and unsafe — values > 255 (the valid
  range is 2–1000 ms) raised `ValueError` before the write.
- `init()`: removed six `if self._poll_for_answer(...): return` guards. They were
  unreachable — `_poll_for_answer` raises on failure and returns `0` on success, so
  the `if` never fired; collapsed to bare calls.
- Inlined three identity pass-through decoders (`_nb_target_detected`,
  `_target_status`, `_reflectance`) that only returned their argument.
- Private DCI/upload helpers (`_dci_read_data`, `_dci_write_data`,
  `_dci_replace_data`, `_send_offset_data`, `_send_xtalk_data`) no longer return a
  bool no caller consumed; they are now `-> None`.
- Docstrings: moved the constructor `Args:` block from the class docstring into
  `__init__`, corrected the `init()` firmware-upload timing to the project's 100 kHz
  soft-I²C reality, and folded `init()`'s indirect `Raises:` into prose (satisfies
  pydoclint DOC304/DOC502).

Treat `vl53l5cx.py` and `_config_bytes.py` as vendored-with-local-modifications
snapshots: don't re-sync from upstream without re-applying these changes.
