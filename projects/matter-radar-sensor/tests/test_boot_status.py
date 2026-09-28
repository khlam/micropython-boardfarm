"""Boot guards, stable Matter endpoints, and the boot status."""

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


@pytest.mark.parametrize(
    ("commissioned", "color"), [(False, "_BOOT_COLOR"), (True, "_OCCUPIED_COLOR")]
)
def test_boot_status_reflects_restored_pairing(
    load_application: Callable[..., SimpleNamespace], commissioned: bool, color: str
):
    """An unpaired boot shows the boot color; a paired one shows occupancy.

    Args:
        load_application: Boots the firmware application.
        commissioned: Whether flash holds a fabric at boot.
        color: Name of the status module constant the pixel shows last.
    """
    boot = load_application(commissioned=commissioned)

    assert boot.application._status._pixel.writes[-1] == getattr(boot.status_module, color)
