---
name: coding-conventions
description: Conventions shared across every language here — API clarity, naming, ordering, error handling, dead code, tests, review checklist. Pair with cpython-syntax, micropython-syntax, or c-syntax.
---

# General principles

Keep public APIs understandable without reading their implementation. Inputs, outputs, side effects, ownership, units, and expected failures should be clear.

Use functions for stateless calculations and transformations. Use classes when there is real state or ownership, such as hardware devices, reusable buffers, connections, or application lifecycle.

Keep dependencies visible. Prefer arguments, constructors, and object-owned resources over hidden globals or import-time initialization.

Prefer simple, explicit code over clever abstractions, especially around hardware, memory, timing, serialization, and concurrency.

Don't preserve the past — in prose or in code. No "replaces …" / "previously …" phrasing in comments; no dead branches, compat shims, or aliases for renamed symbols. Git covers history. Exception: when prior state explains a current workaround or silicon/library quirk that would otherwise look arbitrary.

Comments should explain **why**, not restate the code.

# Naming

Include units in names when useful:

```python
distance_mm
temperature_c
timeout_ms
sample_rate_hz
```

Prefer specific names such as `decode_packet()` or `read_distance_mm()` over vague names such as `process()` or `handle()`.

# Ordering

Order functions and methods so the file reads as a call graph, top down: constructor first, then
the public entry point, then the long-lived tasks it spawns in the same order it spawns them, then
the helpers each task calls. A helper shared by several tasks sits below all of them; a helper used
by one task stays with that task's group. Never interleave a task loop among the helpers it calls.

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

# A test is not a caller

Every function, method, and class must have a caller in `firmware-packages/`, `projects/`, `cpython-packages/`, or `tools/`. A test exercising it does not count. Add the consumer and the API in the same change, or do not add the API.

# Tests

Behavior changes require tests before the change is complete — write them while finalizing the
change, not speculatively while its behavior is still taking shape. A change is not complete, and
should not be merged, until it has tests and passes the coverage gate.

Tests should cover relevant success and failure cases, including:

* device missing;
* invalid identity;
* malformed input;
* bus failure;
* retries and recovery;
* boundaries and saturation.

Do not make production APIs worse merely to simplify mocking.

# Review checklist

Before considering a change complete:

* code is in the correct host, firmware, project, or native layer;
* public APIs make units, side effects, ownership, and failures clear;
* MicroPython code avoids CPython-only dependencies;
* hardware initializes explicitly, not at import time;
* project wiring stays separate from reusable behavior;
* every new callable has a caller outside the tests;
* expected failures are handled specifically;
* unexpected bugs are not swallowed;
* hot MCU loops avoid unnecessary allocation;
* firmware output remains valid protocol data;
* new behavior has deterministic tests;
* vendored/generated code was not needlessly reformatted;
* formatting, linting, type checking, coverage, and tests pass.
