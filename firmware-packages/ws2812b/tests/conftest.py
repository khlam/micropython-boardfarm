"""Host CPython pytest fixtures for ws2812b.

`_reset_stubs` clears recorded pin/NeoPixel stub state between tests.
"""

import machine
import neopixel
import pytest


@pytest.fixture(autouse=True)
def _reset_stubs():
    """Clear shared stub state each test."""
    machine.reset()
    neopixel.reset()
    yield
