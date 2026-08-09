"""End-to-end tests for the Matter example firmware boot and callbacks."""

import _matter
import machine
import neopixel
import pytest

import matter
from matter.schema import Paths

_FABRIC = (1, 0x1234, 0x5678, 0xFFF1, "controller")


def test_supported_boot_builds_pixel_and_reports_ready(load_main):
    boot = load_main()

    assert boot.module.BOARD.name == "ESP32-S3-Zero"
    assert machine.pin_constructions == [(21, machine.Pin.OUT)]
    assert len(neopixel.NeoPixel.instances) == 1
    assert boot.module.pixel.writes == [boot.module.BOOT_COLOR, boot.module.READY_COLOR]
    assert boot.lines == [{"event": "matter", "state": "ready"}]


def test_unsupported_board_fails_before_hardware_setup(load_main):
    with pytest.raises(RuntimeError, match="unsupported board: RP2040"):
        load_main(machine_name="RP2040")

    assert machine.pin_constructions == []
    assert neopixel.NeoPixel.instances == []


def test_commissioned_boot_restores_controller_owned_color(load_main):
    boot = load_main(persisted=_green_state(), fabrics=[_FABRIC])

    assert boot.module.endpoint.on is True
    assert boot.module.endpoint.level == 25
    assert boot.module.pixel.writes[-1] == (0, 25, 0)


def test_show_rejects_stale_commands_but_accepts_equal_stamps(load_main):
    module = load_main().module
    module.pixel.writes.clear()

    module.show((1, 2, 3), 20)
    module.show((4, 5, 6), 19)
    module.show((7, 8, 9), 20)

    assert module.pixel.writes == [(1, 2, 3), (7, 8, 9)]


def test_set_color_renders_then_publishes_attributes_and_power(load_main):
    module = load_main().module
    module.pixel.writes.clear()

    module.set_color((0, 25, 0))

    assert module.pixel.writes == [(0, 25, 0)]
    assert (
        module.endpoint.hue,
        module.endpoint.saturation,
        module.endpoint.level,
        module.endpoint.color_mode,
        module.endpoint.enhanced_color_mode,
        module.endpoint.on,
    ) == (85, 254, 25, matter.ColorMode.HUE_SATURATION, matter.ColorMode.HUE_SATURATION, True)


def test_set_color_does_not_republish_power_when_already_on(load_main, monkeypatch):
    module = load_main(persisted=_green_state(), fabrics=[_FABRIC]).module
    publications = []
    native_publish = _matter.attribute_publish

    def record(endpoint_id, cluster, attribute, value):
        publications.append((cluster, attribute, value))
        native_publish(endpoint_id, cluster, attribute, value)

    monkeypatch.setattr(_matter, "attribute_publish", record)

    module.set_color((25, 0, 0))

    assert all((cluster, attribute) != Paths.ON_OFF for cluster, attribute, _value in publications)
    assert module.endpoint.on is True


def test_remote_writes_render_the_complete_endpoint_state(load_main):
    module = load_main().module
    module.pixel.writes.clear()

    _matter.inject_remote_write(module.endpoint.id, *Paths.ON_OFF, True)
    _matter.inject_remote_write(module.endpoint.id, *Paths.HUE, 85)
    _matter.inject_remote_write(module.endpoint.id, *Paths.SATURATION, 254)
    _matter.inject_remote_write(module.endpoint.id, *Paths.LEVEL, 25)
    _matter.inject_remote_write(module.endpoint.id, *Paths.ENHANCED_COLOR_MODE, 0)

    assert module.pixel.writes[-1] == (0, 25, 0)


@pytest.mark.parametrize(
    "state_code,expected",
    [
        (0, (0, 25, 25)),
        (3, (25, 0, 25)),
        (4, (0, 25, 0)),
    ],
)
def test_commissioning_status_colors_after_start(load_main, state_code, expected):
    module = load_main().module
    module.pixel.writes.clear()

    _matter.inject_commissioning_event(state_code)

    assert module.pixel.writes[-1] == expected


@pytest.mark.parametrize(
    "state_code,expected",
    [
        (0, (0, 25, 25)),
        (3, (25, 0, 25)),
        (4, (0, 25, 0)),
        (2, (25, 0, 0)),
    ],
)
def test_startup_commissioning_events_win_over_boot_state(load_main, state_code, expected):
    boot = load_main(commissioning=[state_code])

    assert boot.module.pixel.writes[-1] == expected
    assert boot.lines[0]["event"] in {"commissioning", "commissioning_window"}
    assert boot.lines[-1] == {"event": "matter", "state": "ready"}


def test_completion_during_start_is_published_after_node_is_started(load_main):
    boot = load_main(commissioning=[1])

    assert boot.module._commissioned[0] is True
    assert boot.module._pending_commissioned_off[0] is None
    assert boot.module.endpoint.on is False
    assert boot.module.pixel.writes[-1] == boot.module.OFF_COLOR


def test_commissioning_failure_is_sticky(load_main):
    module = load_main().module
    module.pixel.writes.clear()

    _matter.inject_commissioning_event(2)
    _matter.inject_commissioning_event(3)
    module.show((99, 88, 77), 10_000)

    assert module._commissioning_failed[0] is True
    assert module.pixel.writes == [module.FAILED_COLOR]


def test_successful_retry_after_a_failure_clears_the_latch(load_main):
    module = load_main().module
    module.pixel.writes.clear()

    _matter.inject_commissioning_event(2)  # SESSION FAILED
    _matter.inject_commissioning_event(1)  # SESSION COMPLETE

    assert module._commissioning_failed[0] is False
    assert module.pixel.writes == [module.FAILED_COLOR, module.OFF_COLOR]


def test_closed_window_restores_commissioned_controller_state(load_main):
    module = load_main(persisted=_green_state(), fabrics=[_FABRIC]).module
    module.pixel.writes.clear()

    _matter.inject_commissioning_event(3)
    _matter.inject_commissioning_event(4)

    assert module.pixel.writes == [module.WINDOW_COLOR, (0, 25, 0)]


def _green_state():
    return {
        (1, *Paths.ON_OFF): True,
        (1, *Paths.LEVEL): 25,
        (1, *Paths.HUE): 85,
        (1, *Paths.SATURATION): 254,
        (1, *Paths.COLOR_MODE): 0,
        (1, *Paths.ENHANCED_COLOR_MODE): 0,
    }
