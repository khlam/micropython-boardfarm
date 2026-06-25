"""GPS read pump for the clock project."""

import asyncio

from boot_status_led import status
from clock_cycle import POLL_SLEEP_MS


async def pump_gps(gps: object, sync: object) -> None:
    """Continuously read GPS lines and keep the RTC synchronized.

    Runs independently of the display program: every poll interval it reads one
    line and feeds it to ``sync``, which sets the RTC on a complete fix and
    flips ``sync.synced``. A read that NACKs flashes the error LED but never
    crashes the loop.

    Args:
        gps: Object with ``readline() -> str | None``.
        sync: :class:`clock_sync.ClockSynchronizer` consuming each line.
    """
    while True:
        try:
            sync.consume(gps.readline())
        except Exception:  # noqa: BLE001 — sensors NACK; never crash the loop
            status.read_err()
        await asyncio.sleep_ms(POLL_SLEEP_MS)
