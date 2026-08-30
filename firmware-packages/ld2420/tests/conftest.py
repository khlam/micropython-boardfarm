"""Shared fixtures for LD2420 driver host tests."""

import asyncio

import machine
import pytest

from ld2420 import LD2420
from ld2420 import ld2420 as ld2420_module
from micropython_stubs import asyncio_extras

_GATE_COUNT = 16


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
    monkeypatch.setattr(ld2420_module, "_ACK_TIMEOUT_MS", 10)
    monkeypatch.setattr(ld2420_module, "_STARTUP_TIMEOUT_MS", 10)
    monkeypatch.setattr(ld2420_module, "_REPORT_TIMEOUT_MS", 10)


@pytest.fixture
def radar():
    """A constructed LD2420 driver against the fake UART, closed after the test."""
    device = LD2420(bus_id=0, tx=0, rx=1)
    yield device
    device.close()


@pytest.fixture
def build_ack():
    """Return a builder assembling one command ACK frame."""

    def _build(command: int, *, status: int = 0, payload: bytes = b"") -> bytes:
        """Assemble the ACK the radar sends back for ``command``.

        The length word counts the echoed command word, the status word, and
        any trailing payload, matching what ``_ack_frame_end`` expects.

        Args:
            command: Command word the radar is answering.
            status: Status word; zero is success.
            payload: Extra bytes the real radar appends after the status.

        Returns:
            The encoded ACK frame.
        """
        body = _u16le(command | ld2420_module._ACK_FLAG) + _u16le(status) + payload
        return (
            ld2420_module._COMMAND_HEADER + _u16le(len(body)) + body + ld2420_module._COMMAND_FOOTER
        )

    return _build


@pytest.fixture
def configuration_acks(build_ack):
    """The three success ACKs the startup sequence expects, in order."""
    return [build_ack(command) for command, _payload in ld2420_module._CONFIGURATION]


@pytest.fixture
def build_report():
    """Return a builder assembling one 45-byte LD2420 energy-mode report."""

    def _build(*, distance_cm: int = 0, present: bool = True, gates: tuple = ()) -> bytes:
        """Assemble one report from a presence flag and a distance.

        Args:
            distance_cm: Reported range in centimetres.
            present: Whether the presence byte marks somebody detected.
            gates: Per-gate energy values; missing gates report zero.

        Returns:
            The encoded 45-byte report frame.
        """
        padded = ([*gates] + [0] * _GATE_COUNT)[:_GATE_COUNT]
        body = bytes((1 if present else 0,)) + _u16le(distance_cm)
        for energy in padded:
            body += _u16le(energy)
        return (
            ld2420_module._REPORT_HEADER + _u16le(len(body)) + body + ld2420_module._REPORT_FOOTER
        )

    return _build


@pytest.fixture
def ready_radar():
    """Return an async helper that brings a driver up inside the caller's loop.

    Bytes arriving while the driver still awaits a command ACK are consumed by
    the ACK reader, exactly as on hardware, so the first report has to be
    delivered once configuration has finished and the reader is parked.

    A driver that parked keeps its wakeup flag bound to the loop it parked on,
    so any test whose next step also awaits has to stay on this one loop.
    """

    async def _ready(device, report: bytes, acks: list) -> None:
        """Configure ``device`` with ``acks``, then hand it ``report``."""
        machine.queue_uart_replies(list(acks))
        ready = asyncio.create_task(device.wait_ready())
        for _ in range(5):
            await asyncio.sleep(0)
        machine.feed_uart_bytes(report)
        await ready

    return _ready


@pytest.fixture
def start_ready(ready_radar):
    """Return a blocking wrapper around ``ready_radar`` for single-step tests."""

    def _start(device, report: bytes, acks: list) -> None:
        """Bring ``device`` up on a loop of its own."""
        asyncio.run(ready_radar(device, report, acks))

    return _start


def _u16le(value: int) -> bytes:
    """Encode one two-byte unsigned value with its low byte first."""
    return bytes((value & 0xFF, value >> 8))
