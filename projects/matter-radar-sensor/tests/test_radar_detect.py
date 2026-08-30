"""Radar detection over the shared UART, and normalization of what it reports."""

import asyncio

import machine
import pytest
from radar import NoRadarError, Radar, Target

from ld2420 import LD2420
from ld2420 import ld2420 as ld2420_module
from ld2450 import LD2450
from ld2450 import ld2450 as ld2450_module

_BUS = {"bus_id": 1, "tx": 5, "rx": 6}


@pytest.fixture(autouse=True)
def _fast_probes(monkeypatch):
    """Shrink the probe budgets so an absent radar is ruled out in milliseconds.

    The LD2420 keeps a generous startup budget: its probe only begins once the
    LD2450 has been ruled out, and the test feeds its first report after that.
    """
    monkeypatch.setattr(LD2450, "STARTUP_TIMEOUT_MS", 5)
    monkeypatch.setattr(LD2450, "REPORT_TIMEOUT_MS", 5)
    monkeypatch.setattr(ld2420_module, "_ACK_TIMEOUT_MS", 5)
    monkeypatch.setattr(LD2420, "STARTUP_TIMEOUT_MS", 500)
    monkeypatch.setattr(LD2420, "REPORT_TIMEOUT_MS", 5)


def test_model_is_unknown_before_detection():
    radar = Radar(**_BUS)
    assert radar.model is None
    assert machine.uart_constructions == []  # constructing claims no hardware


def test_ld2450_answers_first_and_its_targets_pass_through_unchanged():
    async def _run():
        radar = Radar(**_BUS)
        machine.feed_uart_bytes(_ld2450_report((100, 200, -5, 30)))
        await radar.wait_ready()
        return radar, await radar.read_latest()

    radar, targets = asyncio.run(_run())
    assert radar.model == "ld2450"
    assert targets == (ld2450_module.Target(1, 100, 200, -5, 30),)
    assert len(machine.uart_constructions) == 1  # the LD2420 was never probed


def test_ld2420_is_probed_after_the_ld2450_stays_silent():
    async def _run():
        radar = Radar(**_BUS)
        machine.queue_uart_replies(_ld2420_acks())
        ready = asyncio.create_task(radar.wait_ready())
        await _feed_once_ld2420_is_configured(_ld2420_report(distance_cm=145))
        await ready
        return radar, await radar.read_latest()

    radar, targets = asyncio.run(_run())
    assert radar.model == "ld2420"
    # Range only: x and speed are "not measured", not measurements.
    assert targets == (Target(slot=1, x_mm=0, y_mm=1450, speed_cm_s=0, resolution_mm=0),)
    assert machine.uart_constructions[0].deinitialized is True  # LD2450 released first


def test_no_radar_answering_raises_and_releases_every_probe():
    radar = Radar(**_BUS)
    with pytest.raises(NoRadarError):
        asyncio.run(radar.wait_ready())

    assert [uart.deinitialized for uart in machine.uart_constructions] == [True, True]
    assert radar.model is None


def test_detection_oserror_propagates_instead_of_reading_as_absence():
    """`_run_radar()` reports init_err, not no_device, only if this stays an OSError."""
    radar = Radar(**_BUS)
    machine.fail_uart_reads(OSError("bus fault"))

    with pytest.raises(OSError, match="bus fault"):
        asyncio.run(radar.wait_ready())
    assert len(machine.uart_constructions) == 1  # gave up on the first probe


def test_read_timeout_passes_through_as_none():
    async def _run():
        radar = Radar(**_BUS)
        machine.feed_uart_bytes(_ld2450_report((1, 1, 0, 1)))
        await radar.wait_ready()
        await radar.read_latest()  # consume the retained startup report
        return await radar.read_latest()

    assert asyncio.run(_run()) is None


def test_read_oserror_propagates():
    async def _run():
        radar = Radar(**_BUS)
        machine.feed_uart_bytes(_ld2450_report((1, 1, 0, 1)))
        await radar.wait_ready()
        await radar.read_latest()  # consume the retained startup report
        machine.fail_uart_reads(OSError("bus fault"))
        await radar.read_latest()

    with pytest.raises(OSError, match="bus fault"):
        asyncio.run(_run())


def test_close_before_detection_is_a_noop():
    Radar(**_BUS).close()  # no driver to release, no error


def test_close_after_detection_releases_the_detected_driver():
    async def _run():
        radar = Radar(**_BUS)
        machine.feed_uart_bytes(_ld2450_report((1, 1, 0, 1)))
        await radar.wait_ready()
        radar.close()

    asyncio.run(_run())
    assert machine.uart_constructions[0].deinitialized is True


async def _feed_once_ld2420_is_configured(report: bytes) -> None:
    """Hand the LD2420 its first report once it has finished commanding energy mode.

    Bytes arriving earlier are swallowed by the LD2450 probe or by the LD2420's
    own ACK reader, so the report has to wait until the driver is parked.

    Args:
        report: Encoded LD2420 report fed once the command sequence is done.

    Raises:
        AssertionError: The driver never sent its whole command sequence.
    """
    for _ in range(500):
        uarts = machine.uart_constructions
        if len(uarts) > 1 and len(uarts[1].writes) == len(ld2420_module._CONFIGURATION):
            machine.feed_uart_bytes(report)
            return
        await asyncio.sleep(0.001)
    raise AssertionError("the LD2420 never finished its command sequence")


def _ld2450_report(*slots) -> bytes:
    """Assemble one 30-byte LD2450 report from up to three target slots.

    Position and speed are sign-magnitude encoded; resolution is plain.
    """
    body = bytearray()
    for slot in ([*slots, None, None, None])[:3]:
        if slot is None:
            body += bytes(8)
            continue
        *signed, resolution = slot
        for value in signed:
            body += (-value if value < 0 else value | 0x8000).to_bytes(2, "little")
        body += resolution.to_bytes(2, "little")
    return LD2450.HEADER + bytes(body) + LD2450.FOOTER


def _ld2420_acks() -> list:
    """The success ACKs for every command the LD2420 driver sends at startup."""
    acks = []
    for command, _payload in ld2420_module._CONFIGURATION:
        body = _u16le(int(command) | int(ld2420_module._ACK_FLAG)) + _u16le(0)
        acks.append(
            ld2420_module._COMMAND_HEADER + _u16le(len(body)) + body + ld2420_module._COMMAND_FOOTER
        )
    return acks


def _ld2420_report(*, distance_cm: int) -> bytes:
    """Assemble one 45-byte LD2420 energy-mode report showing somebody present."""
    body = b"\x01" + _u16le(distance_cm) + bytes(32)
    return LD2420.HEADER + _u16le(len(body)) + body + LD2420.FOOTER


def _u16le(value: int) -> bytes:
    """Encode one two-byte unsigned value with its low byte first."""
    return bytes((value & 0xFF, value >> 8))
