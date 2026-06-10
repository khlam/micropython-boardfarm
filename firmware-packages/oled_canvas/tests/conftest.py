"""Host CPython pytest fixtures for oled_canvas."""

import pytest
from fake_driver import FakeDriver

from oled_canvas import OledCanvas


@pytest.fixture
def driver():
    """A fresh 128x64 in-memory driver."""
    return FakeDriver(128, 64)


@pytest.fixture
def canvas(driver):
    """An OledCanvas bound to the 128x64 fake driver."""
    return OledCanvas(driver, 128, 64)
