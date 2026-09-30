---
name: cpython-syntax
description: Use when writing or reviewing CPython. This skill outlines CPython conventions.
---

# CPython

## Layout

Order a file: module docstring, imports, constants, public API, private helpers. In test
files, tests come before fixtures.

## APIs
Use Pydantic where an API needs validation or serialization.

## Docstrings
Google style.

## Host code
Validate external input at the boundary: serial, HTTP, WebSocket, configuration, and file
data.

Make thread and async ownership explicit; share work through queues or other clear
synchronization boundaries.

Use standard logging for diagnostics. For batch work, return structured partial failures
when callers need to act on them.

## Tests

The `testing` skill's three kinds map to:

| Kind | Name | Marker |
| --- | --- | --- |
| Unit | `test_<behavior>` | none |
| Behavioral fuzz | `test_fuzz_<invariant>` | `@pytest.mark.fuzz` |
| Smoke | `test_smoke_<result>` | `@pytest.mark.smoke`; the docstring cites the source of the expected result |

Every test is a `@pytest.mark.parametrize` case table, even with one row. Generate fuzz
cases with `random.Random(<fixed seed>)` at module level. Never put `skip`, `skipif`, or
`xfail` on a smoke test. Markers are registered in the root
[pyproject.toml](../../pyproject.toml).
