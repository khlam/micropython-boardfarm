"""Choose the status pixel colour the occupancy product shows when Matter is settled.

The Matter state (pairing, unpaired, off Wi-Fi) outranks these colours on the
pixel; `matter_status_led` decides that. What is left is product health and
occupancy.
"""

# Matter status patterns share this brightness, so every colour on the pixel is
# equally dim.
STATUS_LEVEL = 8

_OCCUPIED_COLOR = (0, 8, 0)
_VACANT_COLOR = (0, 0, 8)
# Solid yellow, which keeps it apart from the amber that blinks while an
# operational node is off Wi-Fi.
_UNHEALTHY_COLOR = (8, 8, 0)


def product_color(*, healthy: bool, occupied: bool) -> tuple:
    """Return the colour for the product's health and occupancy.

    Args:
        healthy: Whether both Matter polling and radar reports are healthy.
        occupied: Whether occupancy is active, including its hold period.

    Returns:
        The RGB color to display.
    """
    if not healthy:
        return _UNHEALTHY_COLOR
    return _OCCUPIED_COLOR if occupied else _VACANT_COLOR
