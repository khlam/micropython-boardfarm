"""Boot guards and stable Matter endpoints."""

from collections.abc import Callable
from types import SimpleNamespace

import machine
import matter_native
import neopixel
import pytest

import matter
from matter.schema import Paths


def test_unsupported_board_fails_before_hardware_setup(
    load_firmware: Callable[..., SimpleNamespace],
):
    """An unsupported board raises at import before any pin or pixel is claimed.

    Args:
        load_firmware: Imports the firmware on the named board.
    """
    with pytest.raises(RuntimeError, match="unsupported board: RP2040"):
        load_firmware(machine_name="RP2040")

    assert machine.pin_constructions == []
    assert neopixel.NeoPixel.instances == []


def test_boot_creates_persistent_endpoints_in_order_and_publishes_occupied(
    load_application: Callable[..., SimpleNamespace],
):
    """Boot creates the occupancy sensor then the hold light, and publishes occupied.

    Args:
        load_application: Boots the firmware application.
    """
    application = load_application().application

    assert (application._occupancy.id, application._occupancy.type) == (
        1,
        matter.EndpointType.OCCUPANCY_SENSOR,
    )
    assert (application._hold_control.id, application._hold_control.type) == (
        2,
        matter.EndpointType.DIMMABLE_LIGHT,
    )
    assert application._occupancy.occupancy == 1
    assert matter_native.attribute_get(application._occupancy.id, *Paths.OCCUPANCY) == 1
