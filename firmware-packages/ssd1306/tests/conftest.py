"""Host CPython pytest fixtures for ssd1306."""

import machine
import pytest
from fake_ssd1306 import FakeSSD1306


@pytest.fixture(autouse=True)
def _reset_devices():
    """Clear the shared machine-stub device registry between tests."""
    machine.reset()
    yield


@pytest.fixture
def fake_oled():
    """Default fake 128x64 OLED registered at 0x3C."""
    dev = FakeSSD1306()
    machine.register_device(0x3C, dev)
    return dev
