"""The occupancy hold: stay occupied for a while after the room empties.

Every input, including the report time, arrives as an argument, so the hold
behaves the same on the board and in host tests.
"""

import time

from micropython import const

# Matter uses light levels from 0 to 254. Map them to a zero-to-ten-minute hold.
_MATTER_LEVEL_MAXIMUM = const(254)
_MAXIMUM_HOLD_MS = const(600_000)


class Hold:
    """Stay occupied until the hold passes after the first empty report.

    The README's occupancy diagram names three states: occupied, holding
    (occupied with the timer running), and vacant.
    """

    def __init__(self) -> None:
        """Start occupied, as the product requires during startup."""
        self.force_occupied()

    def force_occupied(self) -> None:
        """Set occupied and cancel the current hold."""
        self.occupied = True
        self._hold_started_ms = None

    def report(self, *, occupied: bool, now_ms: int, hold_ms: int) -> None:
        """Apply one valid radar report.

        The hold is anchored to the first empty report and measured against the
        hold in effect now, so changing the hold light mid-hold moves the deadline.

        Args:
            occupied: Whether the report counts as occupied.
            now_ms: Monotonic time when the report was received.
            hold_ms: Current hold after the first empty report.
        """
        if occupied:
            self.force_occupied()
            return
        if not self.occupied:
            return
        if self._hold_started_ms is None:
            self._hold_started_ms = now_ms
        if time.ticks_diff(now_ms, self._hold_started_ms) >= hold_ms:
            self.occupied = False
            self._hold_started_ms = None


def hold_ms(*, on: bool, level: int) -> int:
    """Map the hold light's on/off and Matter level to a hold in milliseconds."""
    if not on:
        return 0
    return level * _MAXIMUM_HOLD_MS // _MATTER_LEVEL_MAXIMUM
