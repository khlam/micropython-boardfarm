"""Host tests for what the LD2420 adds to the shared report stream.

Framing, wakeups, timeouts, and the reader lifecycle belong to
``uart_reports`` and are tested there; these cover the LD2420's own UART
settings and one report read end to end after configuration.
"""

import asyncio

import machine

from ld2420 import LD2420, Target


def test_constructor_opens_the_documented_uart_settings():
    radar = LD2420(bus_id=1, tx=4, rx=5)
    uart = machine.uart_constructions[0]
    assert uart.id == 1
    assert uart.baudrate == 115_200
    assert uart.irq_trigger == machine.UART.IRQ_RXIDLE
    assert [pin_id for pin_id, _mode in machine.pin_constructions] == [4, 5]
    radar.close()


def test_reports_read_end_to_end_decode_into_targets(
    radar, build_report, configuration_acks, start_ready
):
    start_ready(radar, build_report(distance_cm=123), configuration_acks)

    assert asyncio.run(radar.read_latest()) == (Target(1230),)


def test_a_configured_radar_is_not_reconfigured_by_a_second_wait_ready(
    radar, build_report, configuration_acks, start_ready
):
    start_ready(radar, build_report(distance_cm=1), configuration_acks)

    asyncio.run(radar.wait_ready())  # second call is a no-op

    assert len(machine.uart_constructions[0].writes) == 3
