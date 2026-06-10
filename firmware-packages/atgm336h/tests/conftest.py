"""Shared fixtures for atgm336h package tests."""

import machine
import neopixel
import pytest


@pytest.fixture(autouse=True)
def _reset_devices() -> None:
    """Clear machine and neopixel state between tests."""
    machine.reset()
    neopixel.reset()
