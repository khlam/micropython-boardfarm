---
name: cpython-syntax
description: Python naming, layout, typing, API shape, and docstring conventions, plus host-side CPython rules for paths, logging, threading, and boundary validation. Use when writing or reviewing Python under cpython-packages/, tools/, or any project viz/ service.
---

# Python

For Python, `pyproject.toml` is authoritative. Ruff currently enforces 4-space indentation, double quotes, 100-character lines, LF endings, absolute imports, and Google-style docstrings.

## Naming and layout

Use:

* `snake_case` for modules, functions, methods, variables, and attributes;
* `CapWords` for classes and exceptions;
* `UPPER_SNAKE_CASE` for constants;
* `_leading_underscore` for private implementation details.

Use the usual file order:

```text
module docstring
imports
constants
public API
private helpers
```

In test files, test functions come before fixtures.

Use absolute imports. Do not use wildcard imports.

## Types and APIs

Production code should use useful type annotations and satisfy the configured type checker.

Keep APIs simple. Do not introduce a config object for a few obvious arguments:

```python
MPU6050(sda=8, scl=9, bus_id=0)
```

Use a config object or enum when options become numerous, shared, or mutually dependent. Prefer named modes over interacting boolean flags.

Pydantic is appropriate for CPython APIs that need validation or serialization. It is not required for firmware.

## Docstrings

Production modules, classes, functions, and methods should use Google-style docstrings.

One-line summary, then `Args:` / `Returns:` / `Raises:` only when they add something. Tests are exempt (`D100`/`D103` in [pyproject.toml](../../pyproject.toml)).

Document what is not obvious from the signature, especially:

* units;
* hardware side effects;
* ownership;
* blocking behavior;
* retry behavior;
* important exceptions;
* non-obvious invariants.

# CPython

Host code may use the full configured Python version and declared dependencies.

Prefer `pathlib` for paths and standard logging for diagnostics.

Make thread and async ownership explicit. Use queues or other clear synchronization boundaries for shared work.

Validate external input at the boundary, including serial, HTTP, WebSocket, configuration, and file data.

For host-side batch work, consider returning structured partial failures when callers need to act on them programmatically.
