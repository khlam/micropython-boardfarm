# STYLE.md

Coding conventions for `micropython-boardfarm`.

This repository includes:

* **CPython** host code under `cpython-packages/`;
* **MicroPython** firmware under `firmware-packages/` and `projects/*/firmware/`;
* **C/C++** for native and performance-sensitive embedded code.

When rules conflict, prefer:

1. automated tooling and tests;
2. `AGENTS.md`;
3. this document;
4. upstream language/runtime conventions;
5. existing style in vendored code.

For Python, `pyproject.toml` is authoritative. Ruff currently enforces 4-space indentation, double quotes, 100-character lines, LF endings, absolute imports, and Google-style docstrings.

## General principles

Keep public APIs understandable without reading their implementation. Inputs, outputs, side effects, ownership, units, and expected failures should be clear.

Use functions for stateless calculations and transformations. Use classes when there is real state or ownership, such as hardware devices, reusable buffers, connections, or application lifecycle.

Keep dependencies visible. Prefer arguments, constructors, and object-owned resources over hidden globals or import-time initialization.

Project wiring belongs in `projects/<project>/firmware/main.py`. Reusable hardware behavior belongs in `firmware-packages/`.

Prefer simple, explicit code over clever abstractions, especially around hardware, memory, timing, serialization, and concurrency.

Do not keep dead code, obsolete aliases, commented-out implementations, or historical comments unless the history explains a current hardware or library workaround.

# Python

## Naming and layout

Use:

* `snake_case` for modules, functions, methods, variables, and attributes;
* `CapWords` for classes and exceptions;
* `UPPER_SNAKE_CASE` for constants;
* `_leading_underscore` for private implementation details.

Include units in names when useful:

```python
distance_mm
temperature_c
timeout_ms
sample_rate_hz
```

Prefer specific names such as `decode_packet()` or `read_distance_mm()` over vague names such as `process()` or `handle()`.

Use the usual file order:

```text
module docstring
imports
constants
public API
private helpers
```

Use absolute imports. Do not use wildcard imports.

## Types and APIs

Production code should use useful type annotations and satisfy the configured type checker.

Keep MicroPython annotations lightweight. Do not add runtime dependencies solely for typing.

Keep APIs simple. Do not introduce a config object for a few obvious arguments:

```python
MPU6050(sda=8, scl=9, bus_id=0)
```

Use a config object or enum when options become numerous, shared, or mutually dependent. Prefer named modes over interacting boolean flags.

Pydantic is appropriate for CPython APIs that need validation or serialization. It is not required for firmware.

On MicroPython, lightweight tuples, dictionaries, buffers, and simple classes are fine when their meaning is clear.

## Docstrings

Production modules, classes, functions, and methods should use Google-style docstrings.

Document what is not obvious from the signature, especially:

* units;
* hardware side effects;
* ownership;
* blocking behavior;
* retry behavior;
* important exceptions;
* non-obvious invariants.

Comments should explain **why**, not restate the code.

# Error handling

Distinguish programming errors from recoverable runtime failures.

Invalid configuration or API misuse should fail immediately with a meaningful exception.

Expected external failures such as sensor NACKs, disconnects, or malformed external input may be recovered from when recovery is part of the application contract.

Catch only exceptions you know how to handle.

Avoid:

```python
except Exception:
    ...
```

when a narrower exception is possible.

Do not hide programming bugs merely to keep a loop running.

Use `DeviceNotFoundError` when expected hardware is absent. Use `OSError` or a more specific exception for genuine I/O failures.

For host-side batch work, consider returning structured partial failures when callers need to act on them programmatically.

# MicroPython

Firmware code must remain compatible with the actual MicroPython runtime.

Do not assume CPython-only modules, `pip`, or `mip`.

Do not claim pins or initialize peripherals at import time.

Use `micropython.const()` for register addresses, command values, and bit masks where appropriate.

Avoid unnecessary allocation in hot loops. Reuse buffers and prefer APIs such as:

```python
readfrom_mem_into(...)
```

over allocating fresh buffers for every sample.

Do not busy-spin indefinitely. Polling loops should sleep or block on useful work.

A driver should normally:

1. create or acquire its bus;
2. find the expected device;
3. verify identity when possible;
4. configure the device;
5. leave the object ready to use.

Drivers may own state such as bus handles, detected addresses, reusable buffers, calibration, and diagnostic flags.

Prefer block hardware transfers where supported.

Return physical units when that is the public API, and make those units obvious.

Firmware stdout is a protocol interface. Do not use raw diagnostic `print()` in JSON-streaming firmware; use the repository's structured `emit()` path.

# CPython

Host code may use the full configured Python version and declared dependencies.

Prefer `pathlib` for paths and standard logging for diagnostics.

Make thread and async ownership explicit. Use queues or other clear synchronization boundaries for shared work.

Validate external input at the boundary, including serial, HTTP, WebSocket, configuration, and file data.

# C and C++

Follow MicroPython's native-code conventions unless preserving third-party source style.

Use:

* 4-space indentation;
* K&R braces;
* braces for every control block;
* `snake_case` for functions and variables;
* `UPPER_SNAKE_CASE` for macros/constants/enums;
* `_t` suffixes for typedefs.

Example:

```c
if (ready) {
    sample();
} else {
    recover();
}
```

Use `size_t` for sizes and fixed-width integers such as `uint8_t` or `uint32_t` for hardware registers and wire formats.

At MicroPython boundaries, use appropriate MicroPython integer and allocation APIs.

Keep ownership explicit. Avoid unnecessary dynamic allocation in MCU hot paths.

For C++:

* keep the MicroPython-facing boundary small;
* use `extern "C"` where required;
* do not allow C++ exceptions to cross C or MicroPython boundaries;
* do not assume exceptions, RTTI, or the full STL are available on every target.

Prefer typed functions or `static inline` functions over function-like macros.

Check return codes and translate native failures into meaningful Python/MicroPython exceptions.

# Vendored and generated code

Do not mechanically restyle vendored code.

Keep vendor modifications minimal and update `VENDOR.md` where present.

Do not hand-edit or reformat generated firmware/configuration blobs.

# Tests

Behavior changes require tests before the change is complete. Per AGENTS.md's testing
policy, do not write those tests until the user confirms the feature is final — write them
while finalizing the change, not speculatively while its behavior is still taking shape. A
change is not complete, and should not be merged, until it has tests and passes the coverage
gate; open a PR, or push past draft, only once you've reached that point, since CI's gated
full suite (`--cov-fail-under=90`) runs on every push to a PR branch and on every push to
main.

Firmware packages should be testable under CPython using the shared MicroPython stubs and deterministic fake devices where practical.

Tests should cover relevant success and failure cases, including:

* device missing;
* invalid identity;
* malformed input;
* bus failure;
* retries and recovery;
* boundaries and saturation.

Do not make production APIs worse merely to simplify mocking.

Once a feature is confirmed final, maintain the repository's configured coverage threshold.

# Dependencies and checks

Firmware dependencies must be MicroPython-compatible and included in the firmware build.

CPython dependencies belong in the appropriate `pyproject.toml`.

Do not install project tooling directly on the host; Docker is the supported development environment.

Initialize tooling with:

```sh
make init
```

Before committing Python changes:

```sh
make precommit
```

Do not silence formatter, linter, type-checker, or test failures with broad ignores. Any ignore should be narrow and intentional.

## Review checklist

Before considering a change complete:

* code is in the correct host, firmware, project, or native layer;
* public APIs make units, side effects, ownership, and failures clear;
* MicroPython code avoids CPython-only dependencies;
* hardware initializes explicitly, not at import time;
* project wiring stays separate from reusable behavior;
* expected failures are handled specifically;
* unexpected bugs are not swallowed;
* hot MCU loops avoid unnecessary allocation;
* firmware output remains valid protocol data;
* new behavior has deterministic tests;
* vendored/generated code was not needlessly reformatted;
* formatting, linting, type checking, coverage, and tests pass.
