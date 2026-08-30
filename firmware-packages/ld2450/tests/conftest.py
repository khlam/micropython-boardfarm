"""Shared fixtures for LD2450 driver host tests."""

import machine
import pytest

from ld2450 import LD2450
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


@pytest.fixture(autouse=True)
def _fast_timeouts(monkeypatch):
    """Shrink the driver's timeout constants so timeout paths run in milliseconds."""
    monkeypatch.setattr(LD2450, "STARTUP_TIMEOUT_MS", 10)
    monkeypatch.setattr(LD2450, "REPORT_TIMEOUT_MS", 10)


@pytest.fixture
def radar():
    """A constructed LD2450 driver against the fake UART, closed after the test."""
    device = LD2450(bus_id=0, tx=0, rx=1)
    yield device
    device.close()


def _encode(value: int) -> int:
    """Encode a signed value into the radar's sign-magnitude raw u16 format."""
    return -value if value < 0 else value | 0x8000


@pytest.fixture
def build_report():
    """Return a builder assembling one 30-byte LD2450 report from up to three slots."""

    def _build(*slots: tuple[int, int, int, int] | None) -> bytes:
        """Assemble one 30-byte report from up to three slots.

        Each slot is an (x_mm, y_mm, speed_cm_s, resolution_mm) tuple or None
        for an empty (all-zero) slot. Fewer than three slots pads the
        remainder with empty slots.
        """
        padded = ([*slots, None, None, None])[:3]
        body = bytearray()
        for slot in padded:
            if slot is None:
                body += bytes(8)
                continue
            x, y, speed, resolution = slot
            body += _encode(x).to_bytes(2, "little")
            body += _encode(y).to_bytes(2, "little")
            body += _encode(speed).to_bytes(2, "little")
            body += resolution.to_bytes(2, "little")
        return LD2450.HEADER + bytes(body) + LD2450.FOOTER

    return _build
