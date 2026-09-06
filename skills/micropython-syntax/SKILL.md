---
name: micropython-syntax
description: MicroPython runtime conventions for MCU firmware — no package manager, no import-time pin claims, const(), buffer reuse, sleep in polling loops, driver init order, and the JSON stdout contract. Use when writing or reviewing code under projects/*/firmware/ or firmware-packages/*/.
---

# MicroPython

Firmware code must remain compatible with the actual MicroPython runtime.

MicroPython has no package manager and no 3rd-party packages to install; all dependencies must be vendored or frozen into firmware via `manifest.py`. Do not use `mip`. Do not assume CPython-only modules or `pip`.

Do not claim pins or initialize peripherals at import time.

Use `micropython.const()` for register addresses, command values, and bit masks where appropriate.

Keep MicroPython annotations lightweight. Do not add runtime dependencies solely for typing.

On MicroPython, lightweight tuples, dictionaries, buffers, and simple classes are fine when their meaning is clear.

Avoid unnecessary allocation in hot loops. Reuse buffers and prefer APIs such as:

```python
readfrom_mem_into(...)
```

over allocating fresh buffers for every sample.

Never spin without `sleep` (≥ 10 ms) — starves the MicroPython scheduler. Polling loops should sleep or block on useful work.

Wrap `sensor.read()` in `try/except` — sensors occasionally NACK. On exception, call `status.read_err()` and `continue` the loop; never let a stray exception crash the loop.

A driver should normally:

1. create or acquire its bus;
2. find the expected device;
3. verify identity when possible;
4. configure the device;
5. leave the object ready to use.

Drivers may own state such as bus handles, detected addresses, reusable buffers, calibration, and diagnostic flags.

Prefer block hardware transfers where supported.

Return physical units when that is the public API, and make those units obvious.

## JSON output schema †

Firmware stdout is a protocol interface. Do not use raw diagnostic `print()` in JSON-streaming firmware; use the repository's structured `emit()` path.

Firmware runs MicroPython (`ujson` built-in); host tests run CPython, where `ujson` is a thin stub that re-exports `json.dumps`. Both sides produce identical compact JSON, so `emit()` is safe to call in either context — but raw `print()` bypasses that contract and silently corrupts the viz parser, which drops any line that isn't valid JSON.

---

† Project-specific quirk — e.g. behavior that differs between the MicroPython firmware runtime and the CPython host-test environment.
