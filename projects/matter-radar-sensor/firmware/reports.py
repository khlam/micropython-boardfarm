"""Decide occupancy and telemetry from radar reports without touching hardware.

Every input, including the report time, arrives as an argument, so these rules
behave the same on the board and in host tests. The application owns the radar,
Matter, and the status pixel, and applies what these objects decide.
"""

import time

from micropython import const

# Ignore targets within this radius because ending tracks can move toward the
# sensor.
_DEAD_ZONE_RADIUS_MM = const(10)
# Matter uses light levels from 0 to 254. Map them to a zero-to-ten-minute hold.
_MATTER_LEVEL_MAXIMUM = const(254)
_MAXIMUM_HOLD_MS = const(600_000)
# Use every radar report for occupancy, but emit telemetry at most twice a second.
_REPORT_INTERVAL_MS = const(500)


def outside_dead_zone(target: object) -> bool:
    """Return whether a target is outside the ignored sensor radius."""
    distance_squared = target.x_mm * target.x_mm + target.y_mm * target.y_mm
    return distance_squared >= _DEAD_ZONE_RADIUS_MM * _DEAD_ZONE_RADIUS_MM


def hold_ms(*, on: bool, level: int) -> int:
    """Map the hold control's on/off and Matter level to a hold in milliseconds."""
    if not on:
        return 0
    return level * _MAXIMUM_HOLD_MS // _MATTER_LEVEL_MAXIMUM


class Occupancy:
    """Stay occupied until the hold passes after the first empty report."""

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
        hold in effect now, so changing the control mid-hold moves the deadline.

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


class ReportThrottle:
    """Pass at most one report per report interval."""

    def __init__(self) -> None:
        """Start with no report sent, so the first one always passes."""
        self._last_ms = None

    def due(self, now_ms: int) -> bool:
        """Return whether to send a report received now, recording it if so.

        Args:
            now_ms: Monotonic time when the report was received.

        Returns:
            Whether the interval has passed since the last report sent.
        """
        if self._last_ms is not None and (
            time.ticks_diff(now_ms, self._last_ms) < _REPORT_INTERVAL_MS
        ):
            return False
        self._last_ms = now_ms
        return True
