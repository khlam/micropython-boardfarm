"""Per-tick runtime state for the clock project."""

import random
import time

from clock_cycle import DisplayCycle
from clock_sync import ClockSynchronizer, emit


class ClockRuntime:
    """Read GPS data, synchronize the RTC, and advance the display cycle."""

    def __init__(
        self,
        gps: object,
        display: object,
        rtc: object,
        *,
        emitter: object | None = None,
        clock: object | None = None,
        rng: object | None = None,
    ) -> None:
        """Bind synchronization state and display cycling to live devices."""
        if emitter is None:
            emitter = emit
        if clock is None:
            clock = time
        if rng is None:
            rng = random
        self._gps = gps
        self._sync = ClockSynchronizer(rtc, emitter=emitter, clock=clock)
        self._display_cycle = DisplayCycle(display, rtc, clock=clock, rng=rng)

    def tick(self) -> None:
        """Process one GPS line and render at most one display update."""
        self._sync.consume(self._gps.readline())
        self._display_cycle.tick(synced=self._sync.synced)
