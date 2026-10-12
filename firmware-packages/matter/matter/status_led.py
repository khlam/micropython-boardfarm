"""Show the Matter device state on one status pixel.

``StatusLed(pixel, level)`` takes the project's NeoPixel and status brightness.
Feed it ``Node.state`` after each poll, the application's colour when it
changes, and ``fail()`` on a failed commissioning attempt; call ``tick()`` from
the loop.

Colour says which state the device is in; blink says whether it is waiting
(slow), working (fast), or stuck (solid). The patterns below are full scale, and
:class:`StatusLed` dims them to the caller's status brightness.
"""

from collections import namedtuple

import utime
from micropython import const
from neopixel import NeoPixel

from matter.state import DeviceState, FabricState, NetworkState

# A blink is lit for ``half_ms``, then dark for as long; 0 means solid.
_Pattern = namedtuple("_Pattern", ("color", "half_ms"))

_OFF = (0, 0, 0)

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
_BOOT = _Pattern(_WHITE, 0)
# Uncommissioned with a window open, or operational and adding a controller.
_PAIRABLE = _Pattern(_PURPLE, _SLOW_MS)
# A commissioner is working through pairing.
_COMMISSIONING = _Pattern(_CYAN, _FAST_MS)
# Uncommissioned and advertising nothing: nobody can reach the device.
_UNREACHABLE = _Pattern(_AMBER, 0)
# Operational, waiting for the Wi-Fi link to come back.
_OFFLINE = _Pattern(_AMBER, _SLOW_MS)

# Played once over any pattern when a commissioning attempt fails.
_FAILURE = _Pattern(_RED, _FLASH_MS)
_FAILURE_MS = _FLASH_COUNT * 2 * _FLASH_MS


class StatusLed:
    """Own one pixel's colour and blink, chosen from the Matter device state.

    The Matter state outranks the application: while the device is pairing,
    unpaired, or off the network, the pixel shows that state. Otherwise it
    shows the application's colour, solid. A failed commissioning attempt
    flashes red over either.

    The caller passes in states and colours as they change and calls
    :meth:`tick` from its loop at least every 50 ms; only :meth:`tick` writes
    the pixel, and only when its colour changes.
    """

    def __init__(self, pixel: NeoPixel, level: int) -> None:
        """Show the boot pattern until the first :meth:`set_state`.

        Args:
            pixel: An initialized one-pixel NeoPixel owned by the caller.
            level: Brightest channel value a status pattern may use, in the
                range 0-255. Application colours are shown as given.
        """
        self._pixel = pixel
        self._level = level
        self._failure = _scaled(_FAILURE, level)
        self._state = None
        self._application = _OFF
        self._pattern = _scaled(_BOOT, level)
        self._pattern_since_ms = utime.ticks_ms()
        self._failure_since_ms = None
        self.tick()

    def set_state(self, state: DeviceState) -> None:
        """Follow a new Matter device state.

        Args:
            state: The node's current :class:`matter.DeviceState`.
        """
        if state == self._state:
            return
        self._state = state
        self._choose_pattern()

    def set_application(self, color: tuple) -> None:
        """Set the colour shown while the Matter state calls for none.

        Args:
            color: Red, green, and blue channel values in the range 0-255.
        """
        if color == self._application:
            return
        self._application = color
        self._choose_pattern()

    def fail(self) -> None:
        """Flash red three times over the current pattern, then resume it."""
        self._failure_since_ms = utime.ticks_ms()

    def tick(self) -> None:
        """Write the colour the patterns call for now, if it changed."""
        now_ms = utime.ticks_ms()
        pattern, since_ms = self._pattern, self._pattern_since_ms
        if self._failure_since_ms is not None:
            if utime.ticks_diff(now_ms, self._failure_since_ms) < _FAILURE_MS:
                pattern, since_ms = self._failure, self._failure_since_ms
            else:
                self._failure_since_ms = None
        # ticks_diff wraps after about six days; a long blink only shifts phase
        # when it does.
        color = _color_at(pattern, utime.ticks_diff(now_ms, since_ms))
        if self._pixel[0] == color:
            return
        self._pixel[0] = color
        self._pixel.write()

    def _choose_pattern(self) -> None:
        """Pick the pattern for the current state, restarting it only on change."""
        if self._state is None:
            return
        pattern = _matter_pattern(self._state)
        if pattern is None:
            pattern = _Pattern(self._application, 0)
        else:
            pattern = _scaled(pattern, self._level)
        if pattern == self._pattern:
            return
        self._pattern = pattern
        self._pattern_since_ms = utime.ticks_ms()


def _matter_pattern(state: DeviceState) -> _Pattern | None:
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


def _scaled(pattern: _Pattern, level: int) -> _Pattern:
    """Dim a full-scale pattern so its brightest channel is at most ``level``.

    Args:
        pattern: Pattern with channel values in the range 0-255.
        level: Brightest channel value to show, in the range 0-255.

    Returns:
        The same timing with every channel scaled down, rounding toward zero.
    """
    red, green, blue = pattern.color
    color = (red * level // 255, green * level // 255, blue * level // 255)
    return _Pattern(color, pattern.half_ms)


def _color_at(pattern: _Pattern, elapsed_ms: int) -> tuple:
    """Return the colour a pattern shows ``elapsed_ms`` after it started.

    Every blink starts lit, so a change of state shows at once.

    Args:
        pattern: The pattern being shown.
        elapsed_ms: Time since the pattern started.

    Returns:
        The pattern's colour, or :data:`_OFF` during a blink's dark half.
    """
    if pattern.half_ms == 0 or elapsed_ms // pattern.half_ms % 2 == 0:
        return pattern.color
    return _OFF
