"""Tests for the Matter example's RGB and attribute conversions."""

from types import SimpleNamespace

import pytest


def test_public_module_exports_color_helpers(color_module):
    assert color_module.__all__ == [
        "ColorMode",
        "matter_to_triple",
        "publish_triple",
        "rgb_to_attributes",
    ]


@pytest.mark.parametrize("on,level", [(False, 254), (True, 0)])
def test_off_or_zero_level_is_black(color_module, on, level):
    endpoint = _endpoint(on=on, level=level)

    assert color_module.matter_to_triple(endpoint) == (0, 0, 0)


@pytest.mark.parametrize(
    "hue,dominant",
    [(0, 0), (43, 1), (85, 1), (128, 2), (170, 2), (212, 0)],
)
def test_hue_saturation_covers_every_sector(color_module, hue, dominant):
    endpoint = _endpoint(
        enhanced_color_mode=color_module.ColorMode.HUE_SATURATION,
        hue=hue,
        saturation=254,
    )

    color = color_module.matter_to_triple(endpoint)

    assert color[dominant] == 255
    assert min(color) == 0


def test_enhanced_hue_mode_and_fractional_level(color_module):
    endpoint = _endpoint(
        enhanced_color_mode=color_module.ColorMode.ENHANCED_HUE_SATURATION,
        hue=0,
        saturation=254,
        level=127,
    )

    assert color_module.matter_to_triple(endpoint) == (128, 0, 0)


@pytest.mark.parametrize(
    "x,y,expected",
    [
        (20494, 21561, (255, 255, 255)),
        (0, 0, (0, 0, 0)),
        (41942, 21627, (255, 0, 0)),
    ],
)
def test_xy_rendering(color_module, x, y, expected):
    endpoint = _endpoint(enhanced_color_mode=color_module.ColorMode.XY, x=x, y=y)

    assert color_module.matter_to_triple(endpoint) == expected


@pytest.mark.parametrize(
    "temperature,expected",
    [(250, (255, 206, 166)), (153, (255, 254, 250)), (500, (255, 137, 14))],
)
def test_temperature_rendering_is_bounded(color_module, temperature, expected):
    endpoint = _endpoint(
        enhanced_color_mode=color_module.ColorMode.COLOR_TEMPERATURE,
        temperature=temperature,
    )

    assert color_module.matter_to_triple(endpoint) == expected


@pytest.mark.parametrize(
    "color,expected",
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
def test_rgb_to_attributes(color_module, color, expected):
    assert color_module.rgb_to_attributes(color) == expected


@pytest.mark.parametrize("color", [(255, 0, 0), (0, 255, 0), (0, 0, 255), (42, 17, 201)])
def test_rgb_round_trip_preserves_color_with_rounding_tolerance(color_module, color):
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


def test_publish_triple_sends_one_named_batch_without_power(color_module):
    endpoint = _RecordingEndpoint(
        hue=0,
        saturation=0,
        color_mode=color_module.ColorMode.COLOR_TEMPERATURE,
        enhanced_color_mode=color_module.ColorMode.COLOR_TEMPERATURE,
        level=254,
        on=False,
    )

    color_module.publish_triple(endpoint, (0, 25, 0))

    assert endpoint.batches == [
        {
            "hue": 85,
            "saturation": 254,
            "color_mode": color_module.ColorMode.HUE_SATURATION,
            "enhanced_color_mode": color_module.ColorMode.HUE_SATURATION,
            "level": 25,
        }
    ]
    assert endpoint.on is False


def test_publish_triple_republishes_the_complete_explicit_batch(color_module):
    endpoint = _RecordingEndpoint(
        hue=85,
        saturation=254,
        color_mode=color_module.ColorMode.HUE_SATURATION,
        enhanced_color_mode=color_module.ColorMode.HUE_SATURATION,
        level=25,
        on=True,
    )

    color_module.publish_triple(endpoint, (0, 25, 0))

    assert len(endpoint.batches) == 1
    assert endpoint.batches[0]["hue"] == 85
    assert endpoint.batches[0]["level"] == 25


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


class _RecordingEndpoint:
    """Endpoint-shaped object that records explicit publication batches."""

    def __init__(self, **values) -> None:
        self.batches = []
        for name, value in values.items():
            setattr(self, name, value)

    def set(self, **attributes) -> None:
        """Record and apply one named publication batch."""
        self.batches.append(attributes)
        for name, value in attributes.items():
            setattr(self, name, value)
