"""Host CPython pytest fixtures for the boot_button package."""

import machine
import pytest
import rp2


@pytest.fixture(autouse=True)
def _reset_devices() -> None:
    """Clear shared machine and rp2 stub state between tests."""
    machine.reset()
    rp2.reset()
