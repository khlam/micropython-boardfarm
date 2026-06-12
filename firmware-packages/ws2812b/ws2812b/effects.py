"""MCU-micropython parametric animation effects for WS2812B strips.

Pure colour maths with no hardware dependency, so the effects run unchanged on
the host under CPython and on the chip under MicroPython. Each effect is a small
stateful object: construct it with its tuning parameters, then call ``frame()``
once per render to get the next ``list[(r, g, b)]`` of length ``count``. The
``Strip`` driver in ``ws2812b.strip`` writes those frames to the LEDs.

Every animation parameter — LED count, brightness ceiling, speed/step, period,
and the colours — is a constructor argument; the only bare literals here are the
fixed constants of the 8-bit RGB / HSV colour model.
"""

import math

# Colour-model constants — fixed by the WS2812B (8-bit channels) and the HSV
# wheel, not tunable animation parameters.
_CHANNEL_MAX = 255  # per-channel value of a WS2812B LED
_SECTORS = 6  # HSV hue wheel sextants
_HALF = 0.5  # midpoint scaler for the breathing cosine
_FULL_TURN = 2 * math.pi  # one breathing cycle, in radians
_CYCLE = 2  # ping-pong period of the colour-fade triangle wave

# Default animation parameters. Every one is overridable per effect; they exist
# so a caller can construct an effect with no arguments and still get something
# sensible, while keeping the literals out of the call sites.
DEFAULT_COUNT = 8
DEFAULT_BRIGHTNESS = 0.3  # ceiling in [0, 1]; WS2812B at full power is blinding
DEFAULT_SPEED = 0.01  # hue fraction advanced per frame (hue rotation)
DEFAULT_STEP = 0.01  # offset/progress advanced per frame (rainbow, fade)
DEFAULT_PERIOD = 60  # frames per full breathing cycle
DEFAULT_COLOR = (0, 128, 255)  # breathing colour (azure)
DEFAULT_START = (255, 0, 0)  # colour-fade start (red)
DEFAULT_END = (0, 0, 255)  # colour-fade end (blue)


def hsv_to_rgb(h: float, s: float, v: float) -> tuple[int, int, int]:
    """Convert an HSV colour to an 8-bit ``(r, g, b)`` tuple.

    Args:
        h: Hue in ``[0, 1)`` (wraps); ``0`` is red, ``1/3`` green, ``2/3`` blue.
        s: Saturation in ``[0, 1]``; ``0`` is greyscale.
        v: Value/brightness in ``[0, 1]``.

    Returns:
        Channel values in ``[0, _CHANNEL_MAX]``. Uses a branchless sextant
        lookup so the conversion stays a single code path.
    """
    sector = int(h * _SECTORS) % _SECTORS
    f = h * _SECTORS - int(h * _SECTORS)
    p = v * (1 - s)
    q = v * (1 - f * s)
    t = v * (1 - (1 - f) * s)
    r, g, b = ((v, t, p), (q, v, p), (p, v, t), (p, q, v), (t, p, v), (v, p, q))[sector]
    return (int(r * _CHANNEL_MAX), int(g * _CHANNEL_MAX), int(b * _CHANNEL_MAX))


class Rainbow:
    """Full-spectrum sweep: each LED a different hue, animated along the strip.

    LED ``i`` takes hue ``(i / count + offset) % 1`` so the whole spectrum is
    laid across the strip at once; ``offset`` advances by ``step`` each frame,
    scrolling the rainbow.
    """

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
    """Continuous hue shift: every LED shares one hue that rotates over time.

    The shared hue advances by ``speed`` (a fraction of the wheel) each frame.
    """

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
    """Sinusoidal brightness pulse of a fixed colour over a configurable period.

    The brightness factor follows ``(1 - cos(2π·n / period)) / 2``, a smooth
    ``0 → 1 → 0`` swell over ``period`` frames, scaled by the brightness ceiling.
    """

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
    """Smooth linear interpolation that ping-pongs between two colours.

    A triangle-wave parameter ``t`` sweeps ``0 → 1 → 0`` so the strip fades from
    ``start`` to ``end`` and back; ``t`` advances by ``step`` each frame.
    """

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
    """Scale each channel of ``rgb`` by ``factor`` (the brightness ceiling)."""
    return (int(rgb[0] * factor), int(rgb[1] * factor), int(rgb[2] * factor))


def _lerp(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    """Per-channel linear interpolation from ``a`` to ``b`` at fraction ``t``."""
    return (
        int(a[0] + (b[0] - a[0]) * t),
        int(a[1] + (b[1] - a[1]) * t),
        int(a[2] + (b[2] - a[2]) * t),
    )
