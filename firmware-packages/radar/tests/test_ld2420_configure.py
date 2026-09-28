"""Host tests for the LD2420 startup command sequence and its ACK handling."""

import asyncio
from collections.abc import Callable

import machine
import pytest

from radar import LD2420, DeviceNotFoundError
from radar.ld2420 import (
    _ACK_BUFFER_LIMIT,
    _COMMAND_FOOTER,
    _COMMAND_HEADER,
    _CONFIGURATION,
    _DISABLE_CONFIG,
    _ENABLE_CONFIG,
    _WRITE_SYSTEM_PARAM,
)


def test_startup_sends_the_energy_mode_sequence(
    ld2420: LD2420,
    build_ld2420_report: Callable[..., bytes],
    configuration_acks: list[bytes],
    start_ready: Callable[[LD2420, bytes, list[bytes]], None],
):
    """Startup writes the enable, energy-mode, and disable command frames in order.

    Args:
        ld2420: The driver under test.
        build_ld2420_report: Encodes the first report fed to the driver.
        configuration_acks: Answers the driver's configuration commands.
        start_ready: Configures the driver and hands it the report.
    """
    start_ready(ld2420, build_ld2420_report(), configuration_acks)

    assert machine.uart_constructions[0].writes == [
        _COMMAND_HEADER + b"\x04\x00" + b"\xff\x00" + b"\x01\x00" + _COMMAND_FOOTER,
        _COMMAND_HEADER + b"\x08\x00" + b"\x12\x00" + b"\x00\x00\x04\x00\x00\x00" + _COMMAND_FOOTER,
        _COMMAND_HEADER + b"\x02\x00" + b"\xfe\x00" + _COMMAND_FOOTER,
    ]


def test_configuration_covers_every_commanded_word():
    """The written frames above are only meaningful if they are the whole sequence."""
    assert [command for command, _payload in _CONFIGURATION] == [
        _ENABLE_CONFIG,
        _WRITE_SYSTEM_PARAM,
        _DISABLE_CONFIG,
    ]


def test_rejected_command_raises_and_closes(ld2420: LD2420, build_ack: Callable[..., bytes]):
    """An ACK with a failure status raises and releases the UART.

    Args:
        ld2420: The driver under test.
        build_ack: Encodes the rejecting ACK.
    """
    machine.queue_uart_replies([build_ack(_ENABLE_CONFIG, status=2)])

    with pytest.raises(DeviceNotFoundError, match="rejected command 0x00ff: 2"):
        asyncio.run(ld2420.wait_ready())
    assert machine.uart_constructions[0].deinitialized is True


def test_missing_ack_raises_and_closes(ld2420: LD2420):
    """A command that is never ACKed raises and releases the UART.

    Args:
        ld2420: The driver under test.
    """
    with pytest.raises(DeviceNotFoundError, match="no LD2420 ACK for command 0x00ff"):
        asyncio.run(ld2420.wait_ready())
    assert machine.uart_constructions[0].deinitialized is True


def test_ack_arriving_after_the_wait_begins_is_accepted(
    ld2420: LD2420, build_ack: Callable[..., bytes]
):
    """The first command is ACKed from the IRQ wakeup, so the second is sent.

    Args:
        ld2420: The driver under test.
        build_ack: Encodes the late ACK.
    """

    async def _run():
        ready = asyncio.create_task(ld2420.wait_ready())
        for _ in range(5):
            await asyncio.sleep(0)
        machine.feed_uart_bytes(build_ack(_ENABLE_CONFIG))
        with pytest.raises(DeviceNotFoundError, match="command 0x0012"):
            await ready

    asyncio.run(_run())
    assert len(machine.uart_constructions[0].writes) == 2


def test_ack_for_another_command_is_skipped(
    ld2420: LD2420,
    build_ld2420_report: Callable[..., bytes],
    build_ack: Callable[..., bytes],
    start_ready: Callable[[LD2420, bytes, list[bytes]], None],
):
    """A stale ACK ahead of the expected one is stepped over, not mistaken for it.

    Args:
        ld2420: The driver under test.
        build_ld2420_report: Encodes the first report fed to the driver.
        build_ack: Encodes the stale and expected ACKs.
        start_ready: Configures the driver and hands it the report.
    """
    acks = [
        build_ack(0x0099) + build_ack(_ENABLE_CONFIG),
        build_ack(_WRITE_SYSTEM_PARAM),
        build_ack(_DISABLE_CONFIG),
    ]
    start_ready(ld2420, build_ld2420_report(distance_cm=30), acks)

    assert len(machine.uart_constructions[0].writes) == 3


def test_ack_with_a_bad_footer_is_not_accepted(ld2420: LD2420, build_ack: Callable[..., bytes]):
    """An ACK whose footer is corrupt doesn't count, so the command times out.

    Args:
        ld2420: The driver under test.
        build_ack: Encodes the ACK before its footer is corrupted.
    """
    malformed = bytearray(build_ack(_ENABLE_CONFIG))
    malformed[-1] ^= 0xFF
    machine.queue_uart_replies([bytes(malformed)])

    with pytest.raises(DeviceNotFoundError, match="no LD2420 ACK"):
        asyncio.run(ld2420.wait_ready())


def test_ack_buffer_is_trimmed_to_its_limit(ld2420: LD2420):
    """Unanswered chatter cannot grow the shared heap without bound.

    Args:
        ld2420: The driver under test.
    """
    machine.feed_uart_bytes(bytes(_ACK_BUFFER_LIMIT + 44))

    assert len(ld2420._drain_ack(bytearray())) == _ACK_BUFFER_LIMIT


def test_write_failure_closes_and_reraises(ld2420: LD2420):
    """A UART write error releases the UART and propagates unchanged.

    Args:
        ld2420: The driver under test.
    """
    machine.fail_uart_writes(OSError("bus fault"))

    with pytest.raises(OSError, match="bus fault"):
        asyncio.run(ld2420.wait_ready())
    assert machine.uart_constructions[0].deinitialized is True
