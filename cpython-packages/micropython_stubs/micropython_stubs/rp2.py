"""Host CPython stub of MicroPython's `rp2` module (RP2040 / RP2350 only)."""

# Mutable BOOTSEL state, driven by set_bootsel() in tests. A single-element list
# keeps the module mutable without a `global` statement, matching the machine stub.
_pressed = [0]


def bootsel_button() -> int:
    """Return 1 while the BOOTSEL button is held, else 0."""
    return _pressed[0]


def set_bootsel(value: int) -> None:
    """Test helper: set the value bootsel_button() reports (1 = held, 0 = released)."""
    _pressed[0] = 1 if value else 0


def reset() -> None:
    """Clear the BOOTSEL state between tests."""
    _pressed[0] = 0
