"""Shared fixtures for ld2450 firmware host tests."""

import pytest

from micropython_stubs import asyncio_extras


@pytest.fixture(autouse=True)
def _micropython_asyncio(monkeypatch: pytest.MonkeyPatch):
    """Install MicroPython-only asyncio names onto the real asyncio module.

    Args:
        monkeypatch: Undoes the installed names after the test.
    """
    asyncio_extras.install(monkeypatch)
