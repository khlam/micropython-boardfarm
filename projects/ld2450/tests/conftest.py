"""Shared fixtures for ld2450 firmware host tests."""

import pytest

from micropython_stubs import asyncio_extras


@pytest.fixture(autouse=True)
def _micropython_asyncio(monkeypatch):
    """Install MicroPython-only asyncio names onto the real asyncio module."""
    asyncio_extras.install(monkeypatch)
