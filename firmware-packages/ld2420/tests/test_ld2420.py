"""Host tests for LD2420 lifecycle: construction, wait_ready(), read_latest(), close()."""

import asyncio

import machine
import pytest

from ld2420 import LD2420, DeviceNotFoundError, Target
from ld2420 import ld2420 as ld2420_module


def test_constructor_opens_uart_and_registers_irq():
    radar = LD2420(bus_id=1, tx=4, rx=5)
    uart = machine.uart_constructions[0]
    assert uart.id == 1
    assert uart.baudrate == 115_200
    assert uart.config["bits"] == 8
    assert uart.config["parity"] is None
    assert uart.config["stop"] == 1
    assert uart.config["rxbuf"] == 512
    assert uart.config["timeout"] == 0
    assert uart.config["timeout_char"] == 0
    assert uart.irq_trigger == machine.UART.IRQ_RXIDLE
    assert uart.irq_hard is False
    assert [pin_id for pin_id, _mode in machine.pin_constructions] == [4, 5]
    radar.close()


def test_wait_ready_happy_path_then_second_call_is_noop(
    radar, build_report, configuration_acks, start_ready
):
    start_ready(radar, build_report(distance_cm=1), configuration_acks)
    asyncio.run(radar.wait_ready())  # second call is a no-op
    assert len(machine.uart_constructions[0].writes) == 3  # not reconfigured


def test_wait_ready_configured_but_silent_raises_and_closes(radar, configuration_acks):
    machine.queue_uart_replies(list(configuration_acks))

    with pytest.raises(DeviceNotFoundError, match="no valid LD2420 report"):
        asyncio.run(radar.wait_ready())
    assert machine.uart_constructions[0].deinitialized is True


def test_wait_ready_oserror_closes_and_reraises(radar):
    machine.fail_uart_reads(OSError("bus fault"))
    with pytest.raises(OSError, match="bus fault"):
        asyncio.run(radar.wait_ready())
    assert machine.uart_constructions[0].deinitialized is True


def test_read_latest_before_wait_ready_raises_runtime_error(radar):
    with pytest.raises(RuntimeError):
        asyncio.run(radar.read_latest())


def test_read_latest_first_call_returns_retained_startup_report(
    radar, build_report, configuration_acks, start_ready
):
    start_ready(radar, build_report(distance_cm=123), configuration_acks)
    assert asyncio.run(radar.read_latest()) == (Target(1230),)


def test_read_latest_newer_report_supersedes_pending(
    radar, build_report, configuration_acks, start_ready
):
    start_ready(radar, build_report(distance_cm=11), configuration_acks)
    machine.feed_uart_bytes(build_report(distance_cm=22))

    assert asyncio.run(radar.read_latest()) == (Target(220),)


def test_read_latest_returns_none_after_timeout(
    radar, build_report, configuration_acks, ready_radar
):
    async def _run():
        await ready_radar(radar, build_report(distance_cm=11), configuration_acks)
        await radar.read_latest()  # consume the retained startup report
        return await radar.read_latest()

    assert asyncio.run(_run()) is None


def test_read_latest_no_target_returns_empty_tuple_not_none(
    radar, build_report, configuration_acks, start_ready
):
    start_ready(radar, build_report(present=False), configuration_acks)
    assert asyncio.run(radar.read_latest()) == ()


def test_read_latest_oserror_reraises_without_closing(
    radar, build_report, configuration_acks, start_ready
):
    start_ready(radar, build_report(distance_cm=11), configuration_acks)
    asyncio.run(radar.read_latest())  # consume the retained startup report

    machine.fail_uart_reads(OSError("bus fault"))
    with pytest.raises(OSError, match="bus fault"):
        asyncio.run(radar.read_latest())
    uart = machine.uart_constructions[0]
    assert uart.deinitialized is False  # unlike wait_ready(), read_latest() doesn't close


def test_read_latest_immediate_timeout_when_budget_already_spent(
    radar, build_report, configuration_acks, start_ready, monkeypatch
):
    start_ready(radar, build_report(distance_cm=11), configuration_acks)
    asyncio.run(radar.read_latest())  # consume the retained startup report

    monkeypatch.setattr(ld2420_module, "_REPORT_TIMEOUT_MS", 0)
    assert asyncio.run(radar.read_latest()) is None


def test_read_latest_wakes_on_report_fed_after_wait_begins(
    radar, build_report, configuration_acks, ready_radar
):
    async def _run():
        await ready_radar(radar, build_report(distance_cm=11), configuration_acks)
        await radar.read_latest()  # consume the retained startup report

        pending = asyncio.create_task(radar.read_latest())
        for _ in range(3):
            await asyncio.sleep(0)
        machine.feed_uart_bytes(build_report(distance_cm=33))
        return await pending

    assert asyncio.run(_run()) == (Target(330),)


def test_concurrent_read_latest_raises_runtime_error(
    radar, build_report, configuration_acks, ready_radar
):
    async def _run():
        await ready_radar(radar, build_report(distance_cm=11), configuration_acks)
        await radar.read_latest()  # consume the retained startup report

        first = asyncio.create_task(radar.read_latest())
        await asyncio.sleep(0)  # let the first call claim the reader and suspend
        with pytest.raises(RuntimeError, match="already has an active reader"):
            await radar.read_latest()
        result = await first
        assert result is None  # first call times out waiting for a new report

    asyncio.run(_run())


def test_concurrent_wait_ready_raises_runtime_error(radar, configuration_acks):
    machine.queue_uart_replies(list(configuration_acks))

    async def _run():
        first = asyncio.create_task(radar.wait_ready())
        await asyncio.sleep(0)  # let the first call claim the reader and suspend
        with pytest.raises(RuntimeError, match="already has an active reader"):
            await radar.wait_ready()
        with pytest.raises(DeviceNotFoundError):
            await first

    asyncio.run(_run())


def test_calls_after_close_raise_runtime_error(radar):
    radar.close()
    with pytest.raises(RuntimeError):
        asyncio.run(radar.wait_ready())
    with pytest.raises(RuntimeError):
        asyncio.run(radar.read_latest())


def test_close_is_idempotent_and_calls_deinit(radar):
    radar.close()
    radar.close()  # no error
    assert machine.uart_constructions[0].deinitialized is True
