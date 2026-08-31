"""Host tests for what the LD2420 adds to the shared report stream.

Framing, wakeups, timeouts, and the reader lifecycle belong to
``radar.stream`` and are tested there; these cover the LD2420's own UART
baud rate and one report read end to end after configuration.
"""

import asyncio

import machine

from radar import Target


def test_constructor_opens_the_documented_baud_rate(ld2420):
    assert machine.uart_constructions[0].baudrate == 115_200


def test_reports_read_end_to_end_decode_into_targets(
    ld2420, build_ld2420_report, configuration_acks, start_ready
):
    start_ready(ld2420, build_ld2420_report(distance_cm=123), configuration_acks)

    assert asyncio.run(ld2420.read_latest()) == (Target(1, 0, 1230, 0, 0),)


def test_a_configured_radar_is_not_reconfigured_by_a_second_wait_ready(
    ld2420, build_ld2420_report, configuration_acks, start_ready
):
    start_ready(ld2420, build_ld2420_report(distance_cm=1), configuration_acks)

    asyncio.run(ld2420.wait_ready())  # second call is a no-op

    assert len(machine.uart_constructions[0].writes) == 3
