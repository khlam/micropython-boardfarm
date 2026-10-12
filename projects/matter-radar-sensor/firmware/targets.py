"""Which radar targets count, and when to send them as telemetry.

Every input, including the report time, arrives as an argument, so these rules
behave the same on the board and in host tests.
"""

import time

from micropython import const

# Ignore targets within this radius because ending tracks can move toward the
# sensor.
_DEAD_ZONE_RADIUS_MM = const(10)
# Use every radar report for occupancy, but emit telemetry at most twice a second.
_REPORT_INTERVAL_MS = const(500)


def outside_dead_zone(target: object) -> bool:
    """Return whether a target is outside the ignored sensor radius."""
    distance_squared = target.x_mm * target.x_mm + target.y_mm * target.y_mm
    return distance_squared >= _DEAD_ZONE_RADIUS_MM * _DEAD_ZONE_RADIUS_MM


class TargetThrottle:
    """Pass at most one changed set of targets per report interval."""

    def __init__(self) -> None:
        """Start with no report sent, so the first one always passes."""
        self._last_ms = None
        self._last_targets = None

    def due(self, targets: tuple, now_ms: int) -> bool:
        """Return whether to send these targets, recording them if so.

        Args:
            targets: Filtered targets from the most recent radar report.
            now_ms: Monotonic time when the report was received.

        Returns:
            Whether the interval has passed and the targets changed.
        """
        if self._last_ms is not None and (
            time.ticks_diff(now_ms, self._last_ms) < _REPORT_INTERVAL_MS
        ):
            return False
        # Advance the interval even when nothing is sent, so an idle timestamp
        # never ages out of ticks_diff's signed range.
        self._last_ms = now_ms
        if targets == self._last_targets:
            return False
        self._last_targets = targets
        return True
