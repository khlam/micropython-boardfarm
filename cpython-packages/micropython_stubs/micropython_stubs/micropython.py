"""Host CPython stub of the `micropython` module — exposes `const` as an identity function.

CPython has no compile-time constant folding analogous to MicroPython's
`micropython.const`, so the stub returns its argument unchanged.
"""


def const(x: int) -> int:
    """Return `x` unchanged."""
    return x
