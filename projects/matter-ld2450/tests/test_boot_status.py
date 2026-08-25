"""Boot, Matter setup, and status-pixel contract tests."""

import json
from types import SimpleNamespace

import machine
import neopixel
import pytest

import matter

_FABRIC = (1, 0x1234, 0x5678, 0xFFF1, "controller")


def test_unsupported_board_fails_before_hardware_setup(load_firmware):
    with pytest.raises(RuntimeError, match="unsupported board: RP2040"):
        load_firmware(machine_name="RP2040")

    assert machine.pin_constructions == []
    assert neopixel.NeoPixel.instances == []


def test_boot_builds_routes_and_stable_matter_endpoints(load_application):
    boot = load_application()
    module = boot.module
    application = boot.application

    assert module.Board(name="ESP32-S3-Zero", uart_id=1, tx=5, rx=6, led_pin=21) == module.BOARD
    assert machine.pin_constructions == [(21, machine.Pin.OUT)]
    assert application._pixel.writes == [module._BOOT_COLOR, module._BOOT_COLOR]
    assert boot.server.port == 80
    assert boot.server.pages == [("/", b"dashboard", "text/html", "gzip")]
    assert boot.server.streams[0][0] == "/ws"
    assert json.loads(boot.server.broadcast.greeting) == {
        "event": "connected",
        "port": "ld2450 uart1",
    }
    assert application._occupancy.id == 1
    assert application._occupancy.type == matter.EndpointType.OCCUPANCY_SENSOR
    assert application._hold_control.id == 2
    assert application._hold_control.type == matter.EndpointType.DIMMABLE_LIGHT
    assert application._occupancy.occupancy == 1
    assert application._hold_control.on is False
    assert application._published_occupancy is True


def test_commissioned_boot_restores_product_status(load_application):
    boot = load_application(fabrics=(_FABRIC,))

    assert boot.application._commissioned is True
    assert boot.application._pixel.writes[-1] == boot.module._OCCUPIED_COLOR


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (matter.Commissioning.STARTED, "_COMMISSIONING_SESSION_COLOR"),
        (matter.Commissioning.OPENED, "_COMMISSIONING_WINDOW_COLOR"),
        (matter.Commissioning.FAILED, "_COMMISSIONING_FAILED_COLOR"),
    ],
)
def test_active_commissioning_states_have_priority(load_application, state, expected):
    boot = load_application(fabrics=(_FABRIC,))
    boot.application._set_radar_health(healthy=False)
    boot.application._on_commissioning(SimpleNamespace(state=state))

    assert boot.application._pixel.writes[-1] == getattr(boot.module, expected)


def test_closed_session_stays_active_until_completion(load_application):
    boot = load_application()
    application = boot.application

    application._on_commissioning(SimpleNamespace(state=matter.Commissioning.STARTED))
    application._on_commissioning(SimpleNamespace(state=matter.Commissioning.CLOSED))
    application._on_commissioning(SimpleNamespace(state=matter.Commissioning.COMPLETE))

    assert application._commissioned is True
    assert application._commissioning_session_active is False
    assert application._pixel.writes[-3:] == [
        boot.module._COMMISSIONING_SESSION_COLOR,
        boot.module._COMMISSIONING_SESSION_COLOR,
        boot.module._OCCUPIED_COLOR,
    ]


def test_closed_uncommissioned_window_is_amber(load_application):
    boot = load_application()

    boot.application._on_commissioning(SimpleNamespace(state=matter.Commissioning.OPENED))
    boot.application._on_commissioning(SimpleNamespace(state=matter.Commissioning.CLOSED))

    assert boot.application._pixel.writes[-1] == boot.module._COMMISSIONING_STOPPED_COLOR


def test_product_status_prioritizes_radar_then_occupancy(load_application):
    boot = load_application(fabrics=(_FABRIC,))
    application = boot.application
    application._pixel.writes.clear()

    application._set_radar_health(healthy=False)
    application._set_radar_health(healthy=False)
    application._set_radar_health(healthy=True)
    application._occupancy_state = boot.module._VACANT
    application._update_status_pixel()

    assert application._pixel.writes == [
        boot.module._RADAR_FAILED_COLOR,
        boot.module._OCCUPIED_COLOR,
        boot.module._VACANT_COLOR,
    ]
