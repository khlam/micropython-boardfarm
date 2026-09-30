"""Tests for the Matter example's RGB and attribute conversions."""

from types import ModuleType, SimpleNamespace

import pytest


def test_public_module_exports_color_helpers(color_module: ModuleType):
    """The color module exports exactly its four helpers.

    Args:
        color_module: The project's color module.
    """
    assert color_module.__all__ == [
        "ColorMode",
        "matter_to_triple",
        "publish_triple",
        "rgb_to_attributes",
    ]


@pytest.mark.parametrize(("on", "level"), [(False, 254), (True, 0)])
def test_off_or_zero_level_is_black(color_module: ModuleType, on: bool, level: int):
    """A light that is off, or at level zero, renders black.

    Args:
        color_module: The project's color module.
        on: The light's on/off state.
        level: The light's level.
    """
    endpoint = _endpoint(on=on, level=level)

    assert color_module.matter_to_triple(endpoint) == (0, 0, 0)


@pytest.mark.parametrize(
    ("hue", "dominant"),
    [(0, 0), (43, 1), (85, 1), (128, 2), (170, 2), (212, 0)],
)
def test_hue_saturation_covers_every_sector(color_module: ModuleType, hue: int, dominant: int):
    """Each hue sector renders fully saturated with its dominant channel at 255.

    Args:
        color_module: The project's color module.
        hue: The Matter hue.
        dominant: The RGB channel index that should be brightest.
    """
    endpoint = _endpoint(
        enhanced_color_mode=color_module.ColorMode.HUE_SATURATION,
        hue=hue,
        saturation=254,
    )

    color = color_module.matter_to_triple(endpoint)

    assert color[dominant] == 255
    assert min(color) == 0


def test_enhanced_hue_mode_and_fractional_level(color_module: ModuleType):
    """Enhanced hue mode renders like hue mode, scaled by the level.

    Args:
        color_module: The project's color module.
    """
    endpoint = _endpoint(
        enhanced_color_mode=color_module.ColorMode.ENHANCED_HUE_SATURATION,
        hue=0,
        saturation=254,
        level=127,
    )

    assert color_module.matter_to_triple(endpoint) == (128, 0, 0)


@pytest.mark.parametrize(
    ("x", "y", "expected"),
    [
        (20494, 21561, (255, 255, 255)),
        (0, 0, (0, 0, 0)),
        (41942, 21627, (255, 0, 0)),
    ],
)
def test_xy_rendering(color_module: ModuleType, x: int, y: int, expected: tuple[int, int, int]):
    """XY mode renders the CIE coordinates as RGB.

    Args:
        color_module: The project's color module.
        x: The Matter CurrentX.
        y: The Matter CurrentY.
        expected: The RGB rendered.
    """
    endpoint = _endpoint(enhanced_color_mode=color_module.ColorMode.XY, x=x, y=y)

    assert color_module.matter_to_triple(endpoint) == expected


@pytest.mark.parametrize(
    ("temperature", "expected"),
    [(250, (255, 206, 166)), (153, (255, 254, 250)), (500, (255, 137, 14))],
)
def test_temperature_rendering_is_bounded(
    color_module: ModuleType, temperature: int, expected: tuple[int, int, int]
):
    """Color temperature mode renders the mireds as RGB, including both range ends.

    Args:
        color_module: The project's color module.
        temperature: The color temperature in mireds.
        expected: The RGB rendered.
    """
    endpoint = _endpoint(
        enhanced_color_mode=color_module.ColorMode.COLOR_TEMPERATURE,
        temperature=temperature,
    )

    assert color_module.matter_to_triple(endpoint) == expected


@pytest.mark.parametrize(
    ("color", "expected"),
    [
        ((0, 0, 0), (0, 0, 0)),
        ((255, 255, 255), (0, 0, 254)),
        ((255, 0, 0), (0, 254, 254)),
        ((0, 255, 0), (85, 254, 254)),
        ((0, 0, 255), (169, 254, 254)),
        ((0, 25, 0), (85, 254, 25)),
        ((-20, 300, 0), (85, 254, 254)),
    ],
)
def test_rgb_to_attributes(
    color_module: ModuleType, color: tuple[int, int, int], expected: tuple[int, int, int]
):
    """RGB converts to Matter hue, saturation, and level, clamping out-of-range channels.

    Args:
        color_module: The project's color module.
        color: The RGB converted.
        expected: Its hue, saturation, and level.
    """
    assert color_module.rgb_to_attributes(color) == expected


@pytest.mark.parametrize("color", [(255, 0, 0), (0, 255, 0), (0, 0, 255), (42, 17, 201)])
def test_rgb_round_trip_preserves_color_with_rounding_tolerance(
    color_module: ModuleType, color: tuple[int, int, int]
):
    """RGB converted to attributes and rendered back stays within 3 per channel.

    Args:
        color_module: The project's color module.
        color: The RGB round-tripped.
    """
    hue, saturation, level = color_module.rgb_to_attributes(color)
    endpoint = _endpoint(
        hue=hue,
        saturation=saturation,
        level=level,
        enhanced_color_mode=color_module.ColorMode.HUE_SATURATION,
    )

    rendered = color_module.matter_to_triple(endpoint)

    channels = zip(rendered, color, strict=True)
    assert all(abs(actual - expected) <= 3 for actual, expected in channels)


def test_publish_triple_sends_one_named_batch_without_power(color_module: ModuleType):
    """publish_triple() sets hue, saturation, both modes, and level in one batch, not power.

    Args:
        color_module: The project's color module.
    """
    batches = []

    def record(**attributes):
        batches.append(attributes)

    endpoint = SimpleNamespace(set=record)

    color_module.publish_triple(endpoint, (0, 25, 0))

    assert batches == [
        {
            "hue": 85,
            "saturation": 254,
            "color_mode": color_module.ColorMode.HUE_SATURATION,
            "enhanced_color_mode": color_module.ColorMode.HUE_SATURATION,
            "level": 25,
        }
    ]


def _endpoint(**changes):
    values = {
        "on": True,
        "level": 254,
        "hue": 0,
        "saturation": 0,
        "x": 20494,
        "y": 21561,
        "temperature": 250,
        "color_mode": 2,
        "enhanced_color_mode": 2,
    }
    values.update(changes)
    return SimpleNamespace(**values)
