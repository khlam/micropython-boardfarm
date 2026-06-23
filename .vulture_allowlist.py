"""Vulture allowlist: names that look unused but are load-bearing.

Used by the pre-commit hook as an additional argument to vulture.
"""

# pytest fixtures: pytest discovers and applies these by name; the test
# function parameter is how it requests the fixture.
monkeypatch  # noqa: F821

# machine.Pin mirrors MicroPython's real signature so client code that
# passes extra positional/keyword args works under the stub too.
args  # noqa: F821
kwargs  # noqa: F821

# utime.sleep_ms keeps the `ms` parameter for API parity; the stub is a no-op.
ms  # noqa: F821
