"""Shared fixtures for the UART report-stream host tests."""

import machine
import pytest
from fake_stream import Stream

from micropython_stubs import asyncio_extras


@pytest.fixture(autouse=True)
def _reset_machine():
    """Clear recorded UART/pin state before and after every test."""
    machine.reset()
    yield
    machine.reset()


@pytest.fixture(autouse=True)
def _micropython_asyncio(monkeypatch):
    """Install MicroPython-only asyncio names onto the real asyncio module."""
    asyncio_extras.install(monkeypatch)


@pytest.fixture
def stream():
    """A constructed stream against the fake UART, closed after the test."""
    device = Stream(bus_id=0, tx=0, rx=1)
    yield device
    device.close()
