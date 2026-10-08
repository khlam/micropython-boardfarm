"""Show the Matter device state on one status pixel."""

import utime
from neopixel import NeoPixel

from matter import DeviceState
from matter_status_led.pattern import (
    BOOT,
    FAILURE,
    FAILURE_MS,
    OFF,
    Pattern,
    color_at,
    matter_pattern,
    scaled,
)


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
        self._failure = scaled(FAILURE, level)
        self._state = None
        self._application = OFF
        self._pattern = scaled(BOOT, level)
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
        color = None
        if self._failure_since_ms is not None:
            elapsed_ms = utime.ticks_diff(now_ms, self._failure_since_ms)
            if elapsed_ms < FAILURE_MS:
                color = color_at(self._failure, elapsed_ms)
            else:
                self._failure_since_ms = None
        if color is None:
            # ticks_diff wraps after about six days; a long blink only shifts
            # phase when it does.
            color = color_at(self._pattern, utime.ticks_diff(now_ms, self._pattern_since_ms))
        if self._pixel[0] == color:
            return
        self._pixel[0] = color
        self._pixel.write()

    def _choose_pattern(self) -> None:
        """Pick the pattern for the current state, restarting it only on change."""
        if self._state is None:
            return
        pattern = matter_pattern(self._state)
        if pattern is None:
            pattern = Pattern(self._application, 0, 0)
        else:
            pattern = scaled(pattern, self._level)
        if pattern == self._pattern:
            return
        self._pattern = pattern
        self._pattern_since_ms = utime.ticks_ms()
