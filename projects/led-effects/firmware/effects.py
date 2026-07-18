"""Parametric animation effects for the led-effects WS2812B strip.

The colour maths has no hardware dependency. Each stateful effect returns the
next list of RGB tuples from ``frame()`` for the project-local strip driver.
"""

import math

_CHANNEL_MAX = 255
_SECTORS = 6
_HALF = 0.5
_FULL_TURN = 2 * math.pi
_CYCLE = 2

DEFAULT_COUNT = 8
DEFAULT_BRIGHTNESS = 0.3
DEFAULT_SPEED = 0.01
DEFAULT_STEP = 0.01
DEFAULT_PERIOD = 60
DEFAULT_COLOR = (0, 128, 255)
DEFAULT_START = (255, 0, 0)
DEFAULT_END = (0, 0, 255)


def hsv_to_rgb(h: float, s: float, v: float) -> tuple[int, int, int]:
    """Convert an HSV colour to an 8-bit ``(r, g, b)`` tuple.

    Args:
        h: Hue in ``[0, 1)`` (wraps); ``0`` is red, ``1/3`` green, ``2/3`` blue.
        s: Saturation in ``[0, 1]``; ``0`` is greyscale.
        v: Value/brightness in ``[0, 1]``.

    Returns:
        Channel values in ``[0, 255]``.
    """
    scaled_hue = (h % 1) * _SECTORS
    sector = int(scaled_hue)
    f = scaled_hue - sector
    p = v * (1 - s)
    q = v * (1 - f * s)
    t = v * (1 - (1 - f) * s)
    if sector == 0:
        r, g, b = v, t, p
    elif sector == 1:
        r, g, b = q, v, p
    elif sector == 2:
        r, g, b = p, v, t
    elif sector == 3:
        r, g, b = p, q, v
    elif sector == 4:
        r, g, b = t, p, v
    else:
        r, g, b = v, p, q
    return (int(r * _CHANNEL_MAX), int(g * _CHANNEL_MAX), int(b * _CHANNEL_MAX))


class Rainbow:
    """Full-spectrum sweep with a different animated hue on each LED."""

    def __init__(
        self,
        count: int = DEFAULT_COUNT,
        *,
        brightness: float = DEFAULT_BRIGHTNESS,
        step: float = DEFAULT_STEP,
    ) -> None:
        """Store the strip length, brightness ceiling, and scroll step."""
        self.count = count
        self.brightness = brightness
        self.step = step
        self._offset = 0.0

    def frame(self) -> list[tuple[int, int, int]]:
        """Return the next frame and advance the scroll offset."""
        colors = [
            _scale(hsv_to_rgb((i / self.count + self._offset) % 1, 1, 1), self.brightness)
            for i in range(self.count)
        ]
        self._offset = (self._offset + self.step) % 1
        return colors


class HueRotate:
    """Continuous hue shift shared by every LED."""

    def __init__(
        self,
        count: int = DEFAULT_COUNT,
        *,
        brightness: float = DEFAULT_BRIGHTNESS,
        speed: float = DEFAULT_SPEED,
    ) -> None:
        """Store the strip length, brightness ceiling, and rotation speed."""
        self.count = count
        self.brightness = brightness
        self.speed = speed
        self._hue = 0.0

    def frame(self) -> list[tuple[int, int, int]]:
        """Return the next uniform-hue frame and advance the hue."""
        rgb = _scale(hsv_to_rgb(self._hue, 1, 1), self.brightness)
        self._hue = (self._hue + self.speed) % 1
        return [rgb] * self.count


class Breathe:
    """Sinusoidal brightness pulse of a fixed colour."""

    def __init__(
        self,
        count: int = DEFAULT_COUNT,
        *,
        color: tuple[int, int, int] = DEFAULT_COLOR,
        brightness: float = DEFAULT_BRIGHTNESS,
        period: int = DEFAULT_PERIOD,
    ) -> None:
        """Store the strip length, pulse colour, brightness ceiling, and period."""
        self.count = count
        self.color = color
        self.brightness = brightness
        self.period = period
        self._frame = 0

    def frame(self) -> list[tuple[int, int, int]]:
        """Return the next pulsed frame and advance the breathing phase."""
        factor = (1 - math.cos(_FULL_TURN * self._frame / self.period)) * _HALF
        rgb = _scale(self.color, self.brightness * factor)
        self._frame = (self._frame + 1) % self.period
        return [rgb] * self.count


class ColorFade:
    """Linear colour interpolation that ping-pongs between two colours."""

    def __init__(
        self,
        count: int = DEFAULT_COUNT,
        *,
        start: tuple[int, int, int] = DEFAULT_START,
        end: tuple[int, int, int] = DEFAULT_END,
        brightness: float = DEFAULT_BRIGHTNESS,
        step: float = DEFAULT_STEP,
    ) -> None:
        """Store the strip length, endpoint colours, brightness ceiling, and step."""
        self.count = count
        self.start = start
        self.end = end
        self.brightness = brightness
        self.step = step
        self._phase = 0.0

    def frame(self) -> list[tuple[int, int, int]]:
        """Return the next interpolated frame and advance the fade phase."""
        t = self._phase if self._phase <= 1 else _CYCLE - self._phase
        rgb = _scale(_lerp(self.start, self.end, t), self.brightness)
        self._phase = (self._phase + self.step) % _CYCLE
        return [rgb] * self.count


def _scale(rgb: tuple[int, int, int], factor: float) -> tuple[int, int, int]:
    """Scale each channel of ``rgb`` by ``factor``."""
    return (int(rgb[0] * factor), int(rgb[1] * factor), int(rgb[2] * factor))


def _lerp(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    """Interpolate each channel from ``a`` to ``b`` at fraction ``t``."""
    return (
        int(a[0] + (b[0] - a[0]) * t),
        int(a[1] + (b[1] - a[1]) * t),
        int(a[2] + (b[2] - a[2]) * t),
    )
