"""Host CPython stub of the `micropython` module — exposes `const` as an identity function.

CPython has no compile-time constant folding analogous to MicroPython's
`micropython.const`, so the stub returns its argument unchanged. The
signature is `(x: object) -> object` to accommodate both integer register
addresses and the occasional `const(...)` over a non-int.
"""


def const(x: object) -> object:
    """Return `x` unchanged."""
    return x
