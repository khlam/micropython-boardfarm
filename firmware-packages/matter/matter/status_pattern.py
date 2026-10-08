"""Colour and blink patterns for each Matter device state.

Pure data and pure functions: nothing here touches a pixel or a clock.

Colour says which state the device is in; blink says whether it is waiting
(slow), working (fast), or stuck (solid). Colours are full scale here, and
:func:`scaled` dims them to the caller's status brightness.
"""

from collections import namedtuple

from micropython import const

from matter.state import DeviceState, FabricState, NetworkState

__all__ = [
    "BOOT",
    "FAILURE",
    "FAILURE_MS",
    "OFF",
    "Pattern",
    "color_at",
    "matter_pattern",
    "scaled",
]

# ``off_ms`` of 0 means solid; ``on_ms`` is then unused.
Pattern = namedtuple("Pattern", ("color", "on_ms", "off_ms"))

OFF = (0, 0, 0)

# Multiples of the 50 ms Matter poll the projects tick from.
_SLOW_MS = const(500)
_FAST_MS = const(100)
_FLASH_MS = const(200)
_FLASH_COUNT = const(3)

_WHITE = (255, 255, 255)
_PURPLE = (255, 0, 255)
_CYAN = (0, 255, 255)
_RED = (255, 0, 0)
_AMBER = (255, 128, 0)

# Firmware running, the stack not polled yet.
BOOT = Pattern(_WHITE, 0, 0)
# Uncommissioned with a window open, or operational and adding a controller.
_PAIRABLE = Pattern(_PURPLE, _SLOW_MS, _SLOW_MS)
# A commissioner is working through pairing.
_COMMISSIONING = Pattern(_CYAN, _FAST_MS, _FAST_MS)
# Uncommissioned and advertising nothing: nobody can reach the device.
_UNREACHABLE = Pattern(_AMBER, 0, 0)
# Operational, waiting for the Wi-Fi link to come back.
_OFFLINE = Pattern(_AMBER, _SLOW_MS, _SLOW_MS)

# Played once over any pattern when a commissioning attempt fails.
FAILURE = Pattern(_RED, _FLASH_MS, _FLASH_MS)
FAILURE_MS = _FLASH_COUNT * 2 * _FLASH_MS


def matter_pattern(state: DeviceState) -> Pattern | None:
    """Return the pattern a Matter device state calls for.

    Pairing outranks the network, which outranks an open window on an
    operational device.

    Args:
        state: A :class:`matter.DeviceState`.

    Returns:
        The full-scale pattern, or None when the device is operational,
        connected, and not pairing, so the application owns the pixel.
    """
    fabric, network, window_open = state
    if fabric == FabricState.COMMISSIONING:
        return _COMMISSIONING
    if fabric == FabricState.UNCOMMISSIONED:
        return _PAIRABLE if window_open else _UNREACHABLE
    if network == NetworkState.DISCONNECTED:
        return _OFFLINE
    if window_open:
        return _PAIRABLE
    return None


def scaled(pattern: Pattern, level: int) -> Pattern:
    """Dim a full-scale pattern so its brightest channel is at most ``level``.

    Args:
        pattern: Pattern with channel values in the range 0-255.
        level: Brightest channel value to show, in the range 0-255.

    Returns:
        The same timing with every channel scaled down, rounding toward zero.
    """
    red, green, blue = pattern.color
    color = (red * level // 255, green * level // 255, blue * level // 255)
    return Pattern(color, pattern.on_ms, pattern.off_ms)


def color_at(pattern: Pattern, elapsed_ms: int) -> tuple:
    """Return the colour a pattern shows ``elapsed_ms`` after it started.

    Every blink starts lit, so a change of state shows at once.

    Args:
        pattern: The pattern being shown.
        elapsed_ms: Time since the pattern started.

    Returns:
        The pattern's colour, or :data:`OFF` during a blink's dark half.
    """
    if pattern.off_ms == 0 or elapsed_ms % (pattern.on_ms + pattern.off_ms) < pattern.on_ms:
        return pattern.color
    return OFF
