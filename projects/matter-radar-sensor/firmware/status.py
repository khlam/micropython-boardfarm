"""Render commissioning and product health on the onboard status pixel."""

from neopixel import NeoPixel

import matter

# Status colors keep commissioning failures distinct from normal commissioning.
# Amber means an uncommissioned node stopped advertising; yellow means a radar
# or Matter synchronization failure.
_BOOT_COLOR = (8, 8, 8)
_OCCUPIED_COLOR = (0, 8, 0)
_COMMISSIONING_WINDOW_COLOR = (8, 0, 8)
_COMMISSIONING_SESSION_COLOR = (0, 8, 8)
_COMMISSIONING_FAILED_COLOR = (8, 0, 0)
_COMMISSIONING_STOPPED_COLOR = (8, 4, 0)
_RADAR_FAILED_COLOR = (8, 8, 0)
_VACANT_COLOR = (0, 0, 8)


class StatusPixel:
    """Own commissioning state and display the highest-priority status."""

    def __init__(self, pixel: NeoPixel) -> None:
        """Retain the initialized pixel and display the boot color.

        Args:
            pixel: One-pixel NeoPixel instance created by the application.
        """
        self._pixel = pixel
        self._commissioned = False
        self._commissioning_state = None
        self._commissioning_session_active = False
        self._occupied = True
        self._healthy = True
        self._set_color(_BOOT_COLOR)

    def set_commissioned(self, *, value: bool) -> None:
        """Set whether boot restored a paired node and refresh the display."""
        self._commissioned = value
        self._update()

    def on_commissioning(self, event: object) -> None:
        """Record one commissioning transition and update the pixel.

        A failure stays visible only until the next event. The Matter package
        opens another window if an uncommissioned node stops advertising, so a
        persistent red light means commissioning continues to fail.

        Args:
            event: Commissioning event delivered by the Matter node.
        """
        state = event.state
        if state == matter.Commissioning.STARTED:
            self._commissioning_session_active = True
        elif state in (matter.Commissioning.COMPLETE, matter.Commissioning.FAILED):
            self._commissioning_session_active = False
        if state == matter.Commissioning.COMPLETE:
            self._commissioned = True
        self._commissioning_state = state
        self._update()

    def update_product(self, *, occupied: bool, healthy: bool) -> None:
        """Display the application's current occupancy and combined health.

        Args:
            occupied: Whether occupancy is active, including its hold period.
            healthy: Whether both Matter polling and radar reports are healthy.
        """
        self._occupied = occupied
        self._healthy = healthy
        self._update()

    def _update(self) -> None:
        """Show the highest-priority commissioning or product state."""
        self._set_color(
            status_color(
                commissioning=self._commissioning_state,
                session_active=self._commissioning_session_active,
                commissioned=self._commissioned,
                healthy=self._healthy,
                occupied=self._occupied,
            )
        )

    def _set_color(self, color: tuple) -> None:
        """Update the onboard status pixel when its color changes."""
        if self._pixel[0] == color:
            return
        self._pixel[0] = color
        self._pixel.write()


def status_color(
    *,
    commissioning: str | None,
    session_active: bool,
    commissioned: bool,
    healthy: bool,
    occupied: bool,
) -> tuple:
    """Return the color for the highest-priority commissioning or product state.

    Commissioning outranks product state. A closed window can mean that
    commissioning started or that the window expired, so the active-session
    flag distinguishes those cases.

    Args:
        commissioning: Most recent commissioning state, or None before any.
        session_active: Whether a commissioning session has started and not ended.
        commissioned: Whether the node has at least one fabric.
        healthy: Whether both Matter polling and radar reports are healthy.
        occupied: Whether occupancy is active, including its hold period.

    Returns:
        The RGB color to display.
    """
    if commissioning == matter.Commissioning.FAILED:
        return _COMMISSIONING_FAILED_COLOR
    if commissioning == matter.Commissioning.OPENED:
        return _COMMISSIONING_WINDOW_COLOR
    if session_active:
        return _COMMISSIONING_SESSION_COLOR
    if not commissioned:
        closed = commissioning == matter.Commissioning.CLOSED
        return _COMMISSIONING_STOPPED_COLOR if closed else _BOOT_COLOR
    if not healthy:
        return _RADAR_FAILED_COLOR
    return _OCCUPIED_COLOR if occupied else _VACANT_COLOR
