"""Host CPython pytest fixtures for the tz_offset package.

The functions are pure, so tests import tz_offset directly with no fake
hardware. ``machine.reset()`` runs between tests only for parity with the other
package suites.
"""

import machine
import pytest


@pytest.fixture(autouse=True)
def _reset_devices() -> None:
    """Clear shared machine-stub state between tests."""
    machine.reset()
