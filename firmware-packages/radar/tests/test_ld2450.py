"""Host tests for what the LD2450 adds to the shared report stream.

Framing, wakeups, timeouts, and the reader lifecycle belong to
``radar.stream`` and are tested there; these cover the LD2450's own UART
settings and one report read end to end.
"""

import asyncio

import machine

from radar import LD2450, Target


def test_constructor_opens_the_documented_uart_settings():
    radar = LD2450(bus_id=1, tx=4, rx=5)
    uart = machine.uart_constructions[0]
    assert uart.id == 1
    assert uart.baudrate == 256_000
    assert uart.irq_trigger == machine.UART.IRQ_RXIDLE
    assert [pin_id for pin_id, _mode in machine.pin_constructions] == [4, 5]
    radar.close()


def test_reports_read_end_to_end_decode_into_targets(ld2450, build_ld2450_report):
    machine.feed_uart_bytes(build_ld2450_report((1, 2, 0, 3)))
    asyncio.run(ld2450.wait_ready())

    assert asyncio.run(ld2450.read_latest()) == (Target(1, 1, 2, 0, 3),)
