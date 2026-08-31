"""Host tests for the stream lifecycle: construction, wait_ready(), read_latest(), close()."""

import asyncio

import machine
import pytest
from fake_stream import Stream, build_report

from radar import DeviceNotFoundError


def test_constructor_opens_uart_and_registers_irq():
    stream = Stream(bus_id=1, tx=4, rx=5)
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
    stream.close()


def test_wait_ready_happy_path_then_second_call_is_noop(stream):
    machine.feed_uart_bytes(build_report())
    asyncio.run(stream.wait_ready())
    asyncio.run(stream.wait_ready())  # second call is a no-op


def test_wait_ready_silent_line_raises_and_closes(stream):
    with pytest.raises(DeviceNotFoundError, match="no valid STREAM report"):
        asyncio.run(stream.wait_ready())
    assert machine.uart_constructions[0].deinitialized is True


def test_wait_ready_oserror_closes_and_reraises(stream):
    machine.fail_uart_reads(OSError("bus fault"))
    with pytest.raises(OSError, match="bus fault"):
        asyncio.run(stream.wait_ready())
    assert machine.uart_constructions[0].deinitialized is True


def test_wait_ready_wakes_on_report_fed_after_wait_begins(stream):
    async def _run():
        wait_task = asyncio.create_task(stream.wait_ready())
        for _ in range(3):
            await asyncio.sleep(0)
        machine.feed_uart_bytes(build_report())
        await wait_task

    asyncio.run(_run())


def test_failed_preparation_closes_before_any_report_is_read():
    class Unprepared(Stream):
        """Refuse the mode this driver decodes."""

        async def _prepare(self) -> None:
            """Raise as a driver whose command sequence was rejected does.

            Raises:
                DeviceNotFoundError: Always.
            """
            raise DeviceNotFoundError("rejected")

    stream = Unprepared(bus_id=0, tx=0, rx=1)
    machine.feed_uart_bytes(build_report())

    with pytest.raises(DeviceNotFoundError, match="rejected"):
        asyncio.run(stream.wait_ready())
    assert machine.uart_constructions[0].deinitialized is True


def test_read_latest_before_wait_ready_raises_runtime_error(stream):
    with pytest.raises(RuntimeError):
        asyncio.run(stream.read_latest())


def test_read_latest_first_call_returns_retained_startup_report(stream):
    machine.feed_uart_bytes(build_report(3))
    asyncio.run(stream.wait_ready())
    assert asyncio.run(stream.read_latest()) == (3,)


def test_read_latest_newer_report_supersedes_pending(stream):
    machine.feed_uart_bytes(build_report(1))
    asyncio.run(stream.wait_ready())
    machine.feed_uart_bytes(build_report(2))

    assert asyncio.run(stream.read_latest()) == (2,)


def test_read_latest_returns_none_after_timeout(stream):
    machine.feed_uart_bytes(build_report())
    asyncio.run(stream.wait_ready())
    asyncio.run(stream.read_latest())  # consume the retained startup report

    assert asyncio.run(stream.read_latest()) is None


def test_read_latest_empty_report_returns_empty_tuple_not_none(stream):
    machine.feed_uart_bytes(build_report(0))
    asyncio.run(stream.wait_ready())
    assert asyncio.run(stream.read_latest()) == ()


def test_read_latest_oserror_reraises_without_closing(stream):
    machine.feed_uart_bytes(build_report())
    asyncio.run(stream.wait_ready())
    asyncio.run(stream.read_latest())  # consume the retained startup report

    machine.fail_uart_reads(OSError("bus fault"))
    with pytest.raises(OSError, match="bus fault"):
        asyncio.run(stream.read_latest())
    uart = machine.uart_constructions[0]
    assert uart.deinitialized is False  # unlike wait_ready(), read_latest() doesn't close


def test_read_latest_immediate_timeout_when_budget_already_spent(stream, monkeypatch):
    machine.feed_uart_bytes(build_report())
    asyncio.run(stream.wait_ready())
    asyncio.run(stream.read_latest())  # consume the retained startup report

    monkeypatch.setattr(Stream, "REPORT_TIMEOUT_MS", 0)
    assert asyncio.run(stream.read_latest()) is None


def test_concurrent_read_latest_raises_runtime_error(stream):
    machine.feed_uart_bytes(build_report())
    asyncio.run(stream.wait_ready())
    asyncio.run(stream.read_latest())  # consume the retained startup report

    async def _run():
        first = asyncio.create_task(stream.read_latest())
        await asyncio.sleep(0)  # let the first call claim the reader and suspend
        with pytest.raises(RuntimeError, match="already has an active reader"):
            await stream.read_latest()
        assert await first is None  # first call times out waiting for a new report

    asyncio.run(_run())


def test_concurrent_wait_ready_raises_runtime_error(stream):
    async def _run():
        first = asyncio.create_task(stream.wait_ready())
        await asyncio.sleep(0)  # let the first call claim the reader and suspend
        with pytest.raises(RuntimeError, match="already has an active reader"):
            await stream.wait_ready()
        with pytest.raises(DeviceNotFoundError):
            await first

    asyncio.run(_run())


def test_calls_after_close_raise_runtime_error(stream):
    stream.close()
    with pytest.raises(RuntimeError):
        asyncio.run(stream.wait_ready())
    with pytest.raises(RuntimeError):
        asyncio.run(stream.read_latest())


def test_close_is_idempotent_and_calls_deinit(stream):
    stream.close()
    stream.close()  # no error
    assert machine.uart_constructions[0].deinitialized is True
