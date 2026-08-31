"""Radar detection over a shared UART, and the one target shape every driver decodes into."""

import asyncio

import machine
import pytest

from radar import LD2420, LD2450, NoRadarError, Target, detect
from radar import ld2420 as ld2420_module

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


def test_ld2450_answers_first_and_its_targets_pass_through_unchanged(build_ld2450_report):
    async def _run():
        machine.feed_uart_bytes(build_ld2450_report((100, 200, -5, 30)))
        model, device = await detect(**_BUS)
        return model, await device.read_latest()

    model, targets = asyncio.run(_run())
    assert model == "ld2450"
    assert targets == (Target(1, 100, 200, -5, 30),)
    assert len(machine.uart_constructions) == 1  # the LD2420 was never probed


def test_ld2420_is_probed_after_the_ld2450_stays_silent(build_ld2420_report, configuration_acks):
    async def _run():
        machine.queue_uart_replies(configuration_acks)
        detecting = asyncio.create_task(detect(**_BUS))
        await _feed_once_ld2420_is_configured(build_ld2420_report(distance_cm=145))
        model, device = await detecting
        return model, await device.read_latest()

    model, targets = asyncio.run(_run())
    assert model == "ld2420"
    # Range only: x and speed are "not measured", not measurements.
    assert targets == (Target(slot=1, x_mm=0, y_mm=1450, speed_cm_s=0, resolution_mm=0),)
    assert machine.uart_constructions[0].deinitialized is True  # LD2450 released first


def test_no_radar_answering_raises_and_releases_every_probe():
    with pytest.raises(NoRadarError):
        asyncio.run(detect(**_BUS))

    assert [uart.deinitialized for uart in machine.uart_constructions] == [True, True]


def test_detection_oserror_propagates_instead_of_reading_as_absence():
    """`_run_radar()` reports init_err, not no_device, only if this stays an OSError."""
    machine.fail_uart_reads(OSError("bus fault"))

    with pytest.raises(OSError, match="bus fault"):
        asyncio.run(detect(**_BUS))
    assert len(machine.uart_constructions) == 1  # gave up on the first probe


def test_read_timeout_passes_through_as_none(build_ld2450_report):
    async def _run():
        machine.feed_uart_bytes(build_ld2450_report((1, 1, 0, 1)))
        _model, device = await detect(**_BUS)
        await device.read_latest()  # consume the retained startup report
        return await device.read_latest()

    assert asyncio.run(_run()) is None


def test_read_oserror_propagates(build_ld2450_report):
    async def _run():
        machine.feed_uart_bytes(build_ld2450_report((1, 1, 0, 1)))
        _model, device = await detect(**_BUS)
        await device.read_latest()  # consume the retained startup report
        machine.fail_uart_reads(OSError("bus fault"))
        await device.read_latest()

    with pytest.raises(OSError, match="bus fault"):
        asyncio.run(_run())


def test_close_releases_the_detected_driver(build_ld2450_report):
    async def _run():
        machine.feed_uart_bytes(build_ld2450_report((1, 1, 0, 1)))
        _model, device = await detect(**_BUS)
        device.close()

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
