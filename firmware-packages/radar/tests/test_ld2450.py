"""Host tests for what the LD2450 adds to the shared report stream.

Framing, wakeups, timeouts, and the reader lifecycle belong to
``radar.stream`` and are tested there; these cover the LD2450's own UART
baud rate and one report read end to end.
"""

import asyncio
from collections.abc import Callable

import machine

from radar import LD2450, Target


def test_constructor_opens_the_documented_baud_rate(ld2450: LD2450):
    """The driver opens its UART at the LD2450's documented 256000 baud.

    Args:
        ld2450: The driver under test.
    """
    assert machine.uart_constructions[0].baudrate == 256_000


def test_reports_read_end_to_end_decode_into_targets(
    ld2450: LD2450, build_ld2450_report: Callable[..., bytes]
):
    """A report arriving on the UART reads back as its decoded targets.

    Args:
        ld2450: The driver under test.
        build_ld2450_report: Encodes the report fed to the driver.
    """
    machine.feed_uart_bytes(build_ld2450_report((1, 2, 0, 3)))
    asyncio.run(ld2450.wait_ready())

    assert asyncio.run(ld2450.read_latest()) == (Target(1, 1, 2, 0, 3),)
