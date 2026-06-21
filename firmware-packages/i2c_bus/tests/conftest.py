"""Host CPython pytest fixtures for i2c_bus."""

import machine
import pytest


@pytest.fixture(autouse=True)
def _reset_machine() -> None:
    """Clear recorded machine state (pin constructions, devices) between tests."""
    machine.reset()
