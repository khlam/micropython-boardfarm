"""End-to-end tests for the Matter example firmware boot and events."""

import machine
import matter_native
import neopixel
import pytest

import matter
from matter.schema import Paths
from micropython_stubs.testing import StopLoopError, json_lines

_FABRIC = (1, 0x1234, 0x5678, 0xFFF1, "controller")


def test_supported_boot_builds_pixel_and_reports_ready(load_main):
    boot = load_main()

    assert boot.module.BOARD.name == "ESP32-S3-Zero"
    assert machine.pin_constructions == [(21, machine.Pin.OUT)]
    assert len(neopixel.NeoPixel.instances) == 1
    assert boot.lines == [{"event": "matter", "state": "ready"}]


def test_poll_loop_reports_each_failure_period_once(load_main, monkeypatch, capsys):
    module = load_main().module
    outcomes = iter((OSError("first"), OSError("repeat"), None, OSError("second")))

    def poll():
        outcome = next(outcomes)
        if outcome is not None:
            raise outcome
        return ()

    monkeypatch.setattr(module.node, "poll", poll)
    monkeypatch.setattr(module.time, "sleep_ms", _stop_after(4))
    capsys.readouterr()

    with pytest.raises(StopLoopError):
        module.run()

    assert [line["message"] for line in json_lines(capsys.readouterr().out)] == [
        "first",
        "second",
    ]


def test_unsupported_board_fails_before_hardware_setup(load_main):
    with pytest.raises(RuntimeError, match="unsupported board: RP2040"):
        load_main(machine_name="RP2040")

    assert machine.pin_constructions == []
    assert neopixel.NeoPixel.instances == []


def test_commissioned_boot_restores_controller_owned_color(load_main):
    boot = load_main(persisted=_green_state(), fabrics=[_FABRIC])

    assert boot.module.endpoint.on is True
    assert boot.module.endpoint.level == 25


def test_set_color_publishes_attributes_and_power(load_main):
    module = load_main().module

    module.set_color((0, 25, 0))

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
    native_publish = matter_native.attributes_publish

    def record(endpoint_id, updates):
        publications.extend(updates)
        native_publish(endpoint_id, updates)

    monkeypatch.setattr(matter_native, "attributes_publish", record)

    module.set_color((25, 0, 0))

    assert all((cluster, attribute) != Paths.ON_OFF for cluster, attribute, _value in publications)
    assert module.endpoint.on is True


def test_set_color_black_does_not_force_power_on(load_main):
    module = load_main().module

    module.set_color((0, 0, 0))

    assert module.endpoint.level == 0
    assert module.endpoint.on is False


def test_set_color_black_turns_off_an_already_lit_endpoint(load_main):
    module = load_main(persisted=_green_state(), fabrics=[_FABRIC]).module

    module.set_color((0, 0, 0))

    assert module.endpoint.on is False


def _green_state():
    return {
        (1, *Paths.ON_OFF): True,
        (1, *Paths.LEVEL): 25,
        (1, *Paths.HUE): 85,
        (1, *Paths.SATURATION): 254,
        (1, *Paths.COLOR_MODE): 0,
        (1, *Paths.ENHANCED_COLOR_MODE): 0,
    }


def _stop_after(count):
    """Return a fake ``time.sleep_ms`` that raises StopLoopError on its ``count``-th call."""
    calls = 0

    def sleep_ms(_delay_ms):
        nonlocal calls
        calls += 1
        if calls == count:
            raise StopLoopError

    return sleep_ms
