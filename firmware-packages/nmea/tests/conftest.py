"""Host CPython pytest fixtures for the nmea package.

The parsers are pure functions, so tests import ``nmea`` directly with no fake
hardware. ``machine.reset()`` runs between tests only for parity with the other
package suites.
"""

import machine
import pytest


@pytest.fixture(autouse=True)
def _reset_devices() -> None:
    """Clear shared machine-stub state between tests."""
    machine.reset()
