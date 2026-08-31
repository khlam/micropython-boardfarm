"""Shared fixtures for the report-stream and radar-driver host tests."""

import asyncio

import machine
import pytest
from fake_stream import Stream

from micropython_stubs import asyncio_extras
from radar import LD2420, LD2450
from radar import ld2420 as ld2420_module

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
    """Shrink every driver's timeout constants so timeout paths run in milliseconds."""
    monkeypatch.setattr(ld2420_module, "_ACK_TIMEOUT_MS", 10)
    for driver_type in (LD2450, LD2420):
        monkeypatch.setattr(driver_type, "STARTUP_TIMEOUT_MS", 10)
        monkeypatch.setattr(driver_type, "REPORT_TIMEOUT_MS", 10)


@pytest.fixture
def stream():
    """A constructed stream against the fake UART, closed after the test."""
    device = Stream(bus_id=0, tx=0, rx=1)
    yield device
    device.close()


@pytest.fixture
def ld2450():
    """A constructed LD2450 driver against the fake UART, closed after the test."""
    device = LD2450(bus_id=0, tx=0, rx=1)
    yield device
    device.close()


@pytest.fixture
def ld2420():
    """A constructed LD2420 driver against the fake UART, closed after the test."""
    device = LD2420(bus_id=0, tx=0, rx=1)
    yield device
    device.close()


@pytest.fixture
def build_ld2450_report():
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


@pytest.fixture
def build_ack():
    """Return a builder assembling one LD2420 command ACK frame."""

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
    """The three success ACKs the LD2420 startup sequence expects, in order."""
    return [build_ack(command) for command, _payload in ld2420_module._CONFIGURATION]


@pytest.fixture
def build_ld2420_report():
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
        return LD2420.HEADER + _u16le(len(body)) + body + LD2420.FOOTER

    return _build


@pytest.fixture
def start_ready():
    """Return a helper that configures a driver and hands it its first report."""

    def _start(device, report: bytes, acks: list) -> None:
        """Bring ``device`` up on a loop of its own."""
        asyncio.run(_bring_up(device, report, acks))

    return _start


async def _bring_up(device, report: bytes, acks: list) -> None:
    """Answer ``device``'s command sequence with ``acks``, then hand it ``report``.

    Bytes arriving while the driver still awaits a command ACK are consumed by
    the ACK reader, exactly as on hardware, so the first report has to be
    delivered once configuration has finished and the reader is parked.
    """
    machine.queue_uart_replies(list(acks))
    ready = asyncio.create_task(device.wait_ready())
    for _ in range(5):
        await asyncio.sleep(0)
    machine.feed_uart_bytes(report)
    await ready


def _encode(value: int) -> int:
    """Encode a signed value into the LD2450's sign-magnitude raw u16 format."""
    return -value if value < 0 else value | 0x8000


def _u16le(value: int) -> bytes:
    """Encode one two-byte unsigned value with its low byte first."""
    return bytes((value & 0xFF, value >> 8))
