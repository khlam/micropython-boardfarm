"""Boot guards, stable Matter endpoints, and the boot status."""

import machine
import neopixel
import pytest

import matter


def test_unsupported_board_fails_before_hardware_setup(load_firmware):
    with pytest.raises(RuntimeError, match="unsupported board: RP2040"):
        load_firmware(machine_name="RP2040")

    assert machine.pin_constructions == []
    assert neopixel.NeoPixel.instances == []


def test_boot_creates_persistent_endpoints_in_order_and_publishes_occupied(load_application):
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
    assert application._published_occupancy is True


@pytest.mark.parametrize(
    ("commissioned", "color"), [(False, "_BOOT_COLOR"), (True, "_OCCUPIED_COLOR")]
)
def test_boot_status_reflects_restored_pairing(load_application, commissioned, color):
    boot = load_application(commissioned=commissioned)

    assert boot.application._status._pixel.writes[-1] == getattr(boot.status_module, color)
