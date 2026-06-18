"""Host CPython pytest fixtures for the max7219 package.

The driver takes plain ``spi``/``cs`` objects, so tests pass local fakes rather
than relying on a ``machine`` SPI stub. ``machine.reset()`` runs between tests
for parity with the other package suites.
"""

import machine
import pytest


@pytest.fixture(autouse=True)
def _reset_devices() -> None:
    """Clear shared machine-stub state between tests."""
    machine.reset()
