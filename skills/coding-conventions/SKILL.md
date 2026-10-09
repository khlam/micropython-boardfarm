---
name: coding-conventions
description: Use whenever writing or reviewing code in any language. This skill outlines conventions shared across every coding language.
---

# General principles

Design public-facing APIs so developers can understand how to use them without needing to inspect the source code.

Use functions for stateless/pure calculations and transformations. Use classes when there is real state or ownership.

Don't preserve the past — in prose or in code. Git covers history. No "replaces …" / "previously …" phrasing in comments; no dead branches, compat shims, or aliases for renamed symbols. Exception: when prior state explains a current workaround or silicon/library quirk that would otherwise look arbitrary.

# Structure

Default every package and project to the composite pattern. If another design pattern fits
the problem better, name it and ask the user.

- **Entry point:** creates the objects, connects them, and runs the program. It holds the
  program's loops, over its objects or to show results, so the states and data flow read
  there.
- **Composite:** holds child objects and loops over them, such as calling one method on each.
- **Leaf:** one thing, such as a device, a state machine, or a rule. It owns its state and
  usually has no loops.

Name each part for what it holds, not for its role.

# Naming

Include units in names when useful:

```
distance_mm
temperature_c
timeout_ms
sample_rate_hz
```

Prefer specific names such as `decode_packet()` or `read_distance_mm()` over vague names such as `process()` or `handle()`.

# Ordering

Order a file so it reads as a call graph: each caller above its helpers, a helper with its only
caller, a shared helper below all its callers. A class opens with its constructor.

# Error handling

Distinguish programming errors from recoverable runtime failures.

Invalid configuration or API misuse should fail immediately with a meaningful exception.

Catch only exceptions you know how to handle, using the narrowest type that fits.

# A test is not a caller

Every function, method, and class must have a caller in `firmware-packages/`, `projects/`, `cpython-packages/`, or `tools/`. A test exercising it does not count. Add the consumer and the API in the same change, or do not add the API.

# Tests

Tests should cover relevant success and failure cases, including:
* malformed input;
* retries and recovery;
* boundaries and saturation.

# Review checklist

* code is in the correct host, firmware, project, or native layer;
* structure is a composite, or the user approved another pattern;
* public APIs make units, side effects, ownership, and failures clear;
* project wiring stays separate from reusable behavior;
* every new callable has a caller outside the tests;
* expected failures are handled specifically;
* unexpected bugs are not swallowed;
* new behavior has deterministic tests;
* vendored/generated code was not needlessly reformatted;
* formatting, linting, type checking, coverage, and tests pass.
