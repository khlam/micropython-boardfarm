"""The product colour the pixel shows once Matter is paired and connected."""

from collections import namedtuple

import pytest

Colour = namedtuple("Colour", ("id", "healthy", "occupied", "color"))


@pytest.mark.parametrize(
    "colour",
    [
        Colour(id="healthy-occupied-is-green", healthy=True, occupied=True, color=(0, 8, 0)),
        Colour(id="healthy-vacant-is-blue", healthy=True, occupied=False, color=(0, 0, 8)),
        Colour(id="unhealthy-occupied-is-yellow", healthy=False, occupied=True, color=(8, 8, 0)),
    ],
    ids=lambda colour: colour.id,
)
def test_product_color_shows_health_before_occupancy(status, colour):
    """Unhealthy radar or Matter polling outranks occupancy."""
    assert status.product_color(healthy=colour.healthy, occupied=colour.occupied) == colour.color


@pytest.fixture
def status(firmware_module):
    """The firmware status module."""
    return firmware_module("status")
