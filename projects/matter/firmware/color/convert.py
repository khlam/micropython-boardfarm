"""Convert between Extended Color Light attributes and RGB byte triples.

Matter has no single colour attribute. Colour lives in three mutually exclusive
representations — hue/saturation, CIE xy, and colour temperature in mireds —
chosen at runtime by EnhancedColorMode, scaled by CurrentLevel and gated by
OnOff. This module collapses that model to one RGB triple and back, so the
project sets its light the same way it would set a bare NeoPixel.

Endpoints are reached through their named attributes only, so nothing here names
a cluster or imports the ``matter`` package. Any object exposing ``on``,
``level``, ``hue``, ``saturation``, ``x``, ``y``, ``temperature``,
``color_mode``, and ``enhanced_color_mode`` satisfies it.
"""

import math

from micropython import const

__all__ = ["ColorMode", "matter_to_triple", "publish_triple", "rgb_to_attributes"]


# Matter protocol values for EnhancedColorMode. Declared here rather than
# imported so colour conversion stays independent of the Matter interface, the
# same way a sensor driver carries its own register addresses.
class ColorMode:
    """Colour Control mode values an Extended Color Light can report."""

    HUE_SATURATION = 0
    XY = 1
    COLOR_TEMPERATURE = 2
    ENHANCED_HUE_SATURATION = 3


_MATTER_MAXIMUM = const(254)
_RGB_MAXIMUM = const(255)
_XY_MAXIMUM = const(65535)
_MIRED_KELVIN_SCALE = const(1_000_000)
_MINIMUM_KELVIN = const(2000)
_MAXIMUM_KELVIN = const(6500)
_MINIMUM_CHROMATICITY_Y = 0.0001
_BLUE_TEMPERATURE_THRESHOLD = 19.0
_SRGB_LINEAR_THRESHOLD = 0.0031308
_HUE_SECTORS = 6.0


def matter_to_triple(endpoint: object) -> tuple:
    """Render one Extended Color Light endpoint as an RGB byte triple.

    Args:
        endpoint: Any object exposing the Extended Color Light attributes by
            name.

    Returns:
        Red, green, and blue channel values in the inclusive range 0-255.
    """
    level = endpoint.level
    if not endpoint.on or level == 0:
        return (0, 0, 0)

    mode = endpoint.enhanced_color_mode
    if mode in (ColorMode.HUE_SATURATION, ColorMode.ENHANCED_HUE_SATURATION):
        color = _hue_saturation_to_rgb(endpoint.hue, endpoint.saturation)
    elif mode == ColorMode.XY:
        color = _xy_to_rgb(endpoint.x, endpoint.y)
    else:
        color = _temperature_to_rgb(endpoint.temperature)

    # Scaled channel by channel rather than through a comprehension: this runs
    # on every controller write, and a MicroPython generator costs a heap frame
    # to save three lines.
    brightness = level / _MATTER_MAXIMUM
    red, green, blue = color
    return (
        _channel_to_byte(red * brightness),
        _channel_to_byte(green * brightness),
        _channel_to_byte(blue * brightness),
    )


def publish_triple(endpoint: object, color: tuple) -> None:
    """Publish an RGB byte triple to an endpoint as hue, saturation, and level.

    Hue, saturation, modes, and level cross into ESP-Matter in one explicit
    batch. Power is left alone, so publishing a colour never turns a light on.

    Args:
        endpoint: Any object exposing the Extended Color Light attributes by
            name.
        color: Red, green, and blue channel values in the range 0-255.
    """
    hue, saturation, level = rgb_to_attributes(color)
    endpoint.set(
        hue=hue,
        saturation=saturation,
        color_mode=ColorMode.HUE_SATURATION,
        enhanced_color_mode=ColorMode.HUE_SATURATION,
        level=level,
    )


def rgb_to_attributes(color: tuple) -> tuple:
    """Convert an RGB byte triple to hue, saturation, and level.

    The triple's brightness folds into the level rather than being discarded, so
    ``(0, 25, 0)`` means green at ten percent exactly as it would on a bare
    NeoPixel and survives a round trip back through :func:`matter_to_triple`.

    Args:
        color: Red, green, and blue channel values in the range 0-255.

    Returns:
        Hue, saturation, and level, each in the inclusive range 0-254.
    """
    red, green, blue = color
    red = _clamp(red / _RGB_MAXIMUM)
    green = _clamp(green / _RGB_MAXIMUM)
    blue = _clamp(blue / _RGB_MAXIMUM)
    peak = max(red, green, blue)
    chroma = peak - min(red, green, blue)
    if chroma == 0.0:
        sector = 0.0
    elif peak == red:
        sector = ((green - blue) / chroma) % _HUE_SECTORS
    elif peak == green:
        sector = (blue - red) / chroma + 2.0
    else:
        sector = (red - green) / chroma + 4.0
    saturation = 0.0 if peak == 0.0 else chroma / peak
    return (
        min(_MATTER_MAXIMUM, int(sector * _MATTER_MAXIMUM / _HUE_SECTORS + 0.5)),
        int(saturation * _MATTER_MAXIMUM + 0.5),
        int(peak * _MATTER_MAXIMUM + 0.5),
    )


def _hue_saturation_to_rgb(hue: int, saturation: int) -> tuple:
    """Convert hue and saturation units to normalized RGB."""
    scaled_hue = hue * _HUE_SECTORS / _MATTER_MAXIMUM
    sector = int(scaled_hue)
    sector %= 6
    chroma = saturation / _MATTER_MAXIMUM
    intermediate = chroma * (1.0 - abs((scaled_hue % 2.0) - 1.0))
    match = 1.0 - chroma
    if sector == 0:
        red, green, blue = chroma, intermediate, 0.0
    elif sector == 1:
        red, green, blue = intermediate, chroma, 0.0
    elif sector == 2:
        red, green, blue = 0.0, chroma, intermediate
    elif sector == 3:
        red, green, blue = 0.0, intermediate, chroma
    elif sector == 4:
        red, green, blue = intermediate, 0.0, chroma
    else:
        red, green, blue = chroma, 0.0, intermediate
    return (red + match, green + match, blue + match)


def _xy_to_rgb(current_x: int, current_y: int) -> tuple:
    """Convert CIE xy coordinates to normalized sRGB."""
    x = current_x / _XY_MAXIMUM
    y = current_y / _XY_MAXIMUM
    if y <= _MINIMUM_CHROMATICITY_Y:
        return (0.0, 0.0, 0.0)

    tristimulus_x = x / y
    tristimulus_y = 1.0
    tristimulus_z = (1.0 - x - y) / y
    red = 3.2406 * tristimulus_x - 1.5372 * tristimulus_y - 0.4986 * tristimulus_z
    green = -0.9689 * tristimulus_x + 1.8758 * tristimulus_y + 0.0415 * tristimulus_z
    blue = 0.0557 * tristimulus_x - 0.2040 * tristimulus_y + 1.0570 * tristimulus_z
    red, green, blue = max(0.0, red), max(0.0, green), max(0.0, blue)
    peak = max(red, green, blue, 1.0)
    return (
        _linear_to_srgb(red / peak),
        _linear_to_srgb(green / peak),
        _linear_to_srgb(blue / peak),
    )


def _temperature_to_rgb(mireds: int) -> tuple:
    """Approximate a bounded colour temperature as normalized sRGB."""
    kelvin = min(_MAXIMUM_KELVIN, max(_MINIMUM_KELVIN, _MIRED_KELVIN_SCALE / mireds))
    temperature = kelvin / 100.0
    red = 255.0
    green = 99.4708025861 * math.log(temperature) - 161.1195681661
    blue = 0.0
    if temperature > _BLUE_TEMPERATURE_THRESHOLD:
        blue = 138.5177312231 * math.log(temperature - 10.0) - 305.0447927307
    return (
        _clamp(red / _RGB_MAXIMUM),
        _clamp(green / _RGB_MAXIMUM),
        _clamp(blue / _RGB_MAXIMUM),
    )


def _linear_to_srgb(value: float) -> float:
    """Apply the standard sRGB transfer curve to one linear channel."""
    if value <= _SRGB_LINEAR_THRESHOLD:
        return 12.92 * value
    return 1.055 * math.pow(value, 1.0 / 2.4) - 0.055


def _channel_to_byte(value: float) -> int:
    """Clamp and round one normalized channel to its byte value."""
    return int(_clamp(value) * _RGB_MAXIMUM + 0.5)


def _clamp(value: float) -> float:
    """Clamp a floating-point channel into the normalized range."""
    return min(1.0, max(0.0, value))
