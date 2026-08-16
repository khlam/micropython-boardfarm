"""Host tests for LD2450 lifecycle: construction, wait_ready(), read_latest(), close()."""

import asyncio

import machine
import pytest

from ld2450 import LD2450, DeviceNotFoundError, Target
from ld2450 import ld2450 as ld2450_module


def test_constructor_opens_uart_and_registers_irq():
    radar = LD2450(bus_id=1, tx=4, rx=5)
    uart = machine.uart_constructions[0]
    assert uart.id == 1
    assert uart.baudrate == 256_000
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


def test_wait_ready_happy_path_then_second_call_is_noop(radar, build_report):
    machine.feed_uart_bytes(build_report((1, 2, 0, 3)))
    asyncio.run(radar.wait_ready())
    asyncio.run(radar.wait_ready())  # second call is a no-op


def test_wait_ready_silent_line_raises_and_closes(radar):
    with pytest.raises(DeviceNotFoundError):
        asyncio.run(radar.wait_ready())
    uart = machine.uart_constructions[0]
    assert uart.deinitialized is True


def test_wait_ready_oserror_closes_and_reraises(radar):
    machine.fail_uart_reads(OSError("bus fault"))
    with pytest.raises(OSError, match="bus fault"):
        asyncio.run(radar.wait_ready())
    uart = machine.uart_constructions[0]
    assert uart.deinitialized is True


def test_wait_ready_wakes_on_report_fed_after_wait_begins(radar, build_report):
    async def _run():
        wait_task = asyncio.create_task(radar.wait_ready())
        for _ in range(3):
            await asyncio.sleep(0)
        machine.feed_uart_bytes(build_report((9, 9, 0, 9)))
        await wait_task

    asyncio.run(_run())


def test_read_latest_before_wait_ready_raises_runtime_error(radar):
    with pytest.raises(RuntimeError):
        asyncio.run(radar.read_latest())


def test_read_latest_first_call_returns_retained_startup_report(radar, build_report):
    machine.feed_uart_bytes(build_report((1, 2, 0, 3)))
    asyncio.run(radar.wait_ready())
    targets = asyncio.run(radar.read_latest())
    assert targets == (Target(1, 1, 2, 0, 3),)


def test_read_latest_newer_report_supersedes_pending(radar, build_report):
    machine.feed_uart_bytes(build_report((1, 1, 0, 1)))
    asyncio.run(radar.wait_ready())
    machine.feed_uart_bytes(build_report((2, 2, 0, 2)))

    targets = asyncio.run(radar.read_latest())
    assert targets == (Target(1, 2, 2, 0, 2),)


def test_read_latest_returns_none_after_timeout(radar, build_report):
    machine.feed_uart_bytes(build_report((1, 1, 0, 1)))
    asyncio.run(radar.wait_ready())
    asyncio.run(radar.read_latest())  # consume the retained startup report

    assert asyncio.run(radar.read_latest()) is None


def test_read_latest_no_targets_returns_empty_tuple_not_none(radar, build_report):
    machine.feed_uart_bytes(build_report())
    asyncio.run(radar.wait_ready())
    assert asyncio.run(radar.read_latest()) == ()


def test_read_latest_oserror_reraises_without_closing(radar, build_report):
    machine.feed_uart_bytes(build_report((1, 1, 0, 1)))
    asyncio.run(radar.wait_ready())
    asyncio.run(radar.read_latest())  # consume the retained startup report

    machine.fail_uart_reads(OSError("bus fault"))
    with pytest.raises(OSError, match="bus fault"):
        asyncio.run(radar.read_latest())
    uart = machine.uart_constructions[0]
    assert uart.deinitialized is False  # unlike wait_ready(), read_latest() doesn't close


def test_read_latest_immediate_timeout_when_budget_already_spent(radar, build_report, monkeypatch):
    machine.feed_uart_bytes(build_report((1, 1, 0, 1)))
    asyncio.run(radar.wait_ready())
    asyncio.run(radar.read_latest())  # consume the retained startup report

    monkeypatch.setattr(ld2450_module, "_REPORT_TIMEOUT_MS", 0)
    assert asyncio.run(radar.read_latest()) is None


def test_concurrent_read_latest_raises_runtime_error(radar, build_report):
    machine.feed_uart_bytes(build_report((1, 1, 0, 1)))
    asyncio.run(radar.wait_ready())
    asyncio.run(radar.read_latest())  # consume the retained startup report

    async def _run():
        first = asyncio.create_task(radar.read_latest())
        await asyncio.sleep(0)  # let the first call claim the reader and suspend
        with pytest.raises(RuntimeError, match="already has an active reader"):
            await radar.read_latest()
        result = await first
        assert result is None  # first call times out waiting for a new report

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
    uart = machine.uart_constructions[0]
    assert uart.deinitialized is True
