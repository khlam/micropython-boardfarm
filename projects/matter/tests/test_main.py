"""End-to-end tests for the Matter example firmware boot and events."""

import json

import _matter
import machine
import neopixel
import pytest

import matter
from matter.schema import Paths

_FABRIC = (1, 0x1234, 0x5678, 0xFFF1, "controller")


class StopLoopError(Exception):
    """Escape the firmware's intentional infinite polling loop."""


def test_supported_boot_builds_pixel_and_reports_ready(load_main):
    boot = load_main()

    assert boot.module.BOARD.name == "ESP32-S3-Zero"
    assert machine.pin_constructions == [(21, machine.Pin.OUT)]
    assert len(neopixel.NeoPixel.instances) == 1
    # Nothing was reported during startup, so the boot baseline is all the board
    # can honestly claim; a real one has a window open by this point.
    assert boot.module.pixel.writes == [boot.module.BOOT_COLOR, boot.module.BOOT_COLOR]
    assert boot.lines == [{"event": "matter", "state": "ready"}]


def test_poll_loop_reports_each_failure_period_once_and_preserves_pixel(
    load_main, monkeypatch, capsys
):
    boot = load_main()
    module = boot.module
    pixel_writes = list(module.pixel.writes)
    outcomes = iter((OSError("first"), OSError("repeat"), None, OSError("second")))

    def poll():
        outcome = next(outcomes)
        if outcome is not None:
            raise outcome
        return ()

    sleeps = 0

    def stop_after_four_polls(_delay_ms):
        nonlocal sleeps
        sleeps += 1
        if sleeps == 4:
            raise StopLoopError

    monkeypatch.setattr(module.node, "poll", poll)
    monkeypatch.setattr(module.time, "sleep_ms", stop_after_four_polls)
    capsys.readouterr()

    with pytest.raises(StopLoopError):
        module.run()

    assert module.pixel.writes == pixel_writes
    assert [line["message"] for line in _json_lines(capsys.readouterr().out)] == [
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
    native_publish = _matter.attributes_publish

    def record(endpoint_id, updates):
        publications.extend(updates)
        native_publish(endpoint_id, updates)

    monkeypatch.setattr(_matter, "attributes_publish", record)

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
    module.pixel.writes.clear()

    module.set_color(module.OFF_COLOR)

    assert module.endpoint.on is False
    assert module.pixel.writes == [module.OFF_COLOR]


def test_remote_writes_render_the_complete_endpoint_state(load_main):
    module = load_main().module
    module.pixel.writes.clear()

    _matter.inject_remote_write(module.endpoint.id, *Paths.ON_OFF, True)
    _matter.inject_remote_write(module.endpoint.id, *Paths.HUE, 85)
    _matter.inject_remote_write(module.endpoint.id, *Paths.SATURATION, 254)
    _matter.inject_remote_write(module.endpoint.id, *Paths.LEVEL, 25)
    _matter.inject_remote_write(module.endpoint.id, *Paths.ENHANCED_COLOR_MODE, 0)
    module.handle_events(module.node.poll())

    assert module.pixel.writes[-1] == (0, 25, 0)


def test_controller_color_render_skips_the_last_rendered_colour(load_main):
    module = load_main().module
    module.pixel.writes.clear()

    module._show_controller_color()
    module.pixel.writes.clear()
    module._show_controller_color()

    assert module.pixel.writes == []


def test_remote_write_burst_skips_renders_the_active_mode_cannot_show(load_main):
    module = load_main().module
    module.pixel.writes.clear()

    _matter.inject_remote_write(module.endpoint.id, *Paths.ON_OFF, True)
    _matter.inject_remote_write(module.endpoint.id, *Paths.HUE, 85)
    _matter.inject_remote_write(module.endpoint.id, *Paths.SATURATION, 254)
    _matter.inject_remote_write(module.endpoint.id, *Paths.LEVEL, 25)
    _matter.inject_remote_write(module.endpoint.id, *Paths.ENHANCED_COLOR_MODE, 0)
    module.handle_events(module.node.poll())

    assert module.pixel.writes[-1] == (0, 25, 0)
    assert len(module.pixel.writes) == 1


@pytest.mark.parametrize(
    "state_code,expected",
    [
        (0, (0, 25, 25)),
        (3, (25, 0, 25)),
        (4, (25, 12, 0)),
    ],
)
def test_commissioning_status_colors_after_start(load_main, state_code, expected):
    module = load_main().module
    module.pixel.writes.clear()

    _matter.inject_commissioning_event(state_code)
    module.handle_events(module.node.poll())

    assert module.pixel.writes[-1] == expected


def test_window_closing_for_a_commissioner_is_not_the_window_running_out(load_main):
    module = load_main().module
    module.pixel.writes.clear()

    _matter.inject_commissioning_event(0)  # SESSION STARTED
    _matter.inject_commissioning_event(4)  # WINDOW CLOSED, taken by that session
    module.handle_events(module.node.poll())

    assert module.pixel.writes == [module.SESSION_COLOR, module.SESSION_COLOR]


def test_window_running_out_unpaired_is_not_reported_as_ready(load_main):
    module = load_main().module
    module.pixel.writes.clear()

    _matter.inject_commissioning_event(3)  # WINDOW OPENED
    _matter.inject_commissioning_event(4)  # WINDOW CLOSED with nobody connected
    module.handle_events(module.node.poll())

    assert module.pixel.writes == [module.STALLED_COLOR]


@pytest.mark.parametrize(
    "state_code,expected",
    [
        (0, (0, 25, 25)),
        (3, (25, 0, 25)),
        (4, (25, 12, 0)),
        (2, (25, 0, 0)),
    ],
)
def test_startup_commissioning_events_win_over_boot_state(load_main, state_code, expected):
    boot = load_main(commissioning=[state_code])
    boot.module.handle_events(boot.module.node.poll())

    assert boot.module.pixel.writes[-1] == expected
    assert boot.lines == [{"event": "matter", "state": "ready"}]


@pytest.mark.parametrize(
    "state,expected",
    [
        (matter.Commissioning.STARTED, (0, 25, 25)),
        (matter.Commissioning.OPENED, (25, 0, 25)),
    ],
)
def test_show_post_start_state_renders_the_transition_seen_during_startup(
    load_main, state, expected
):
    module = load_main().module
    module.pixel.writes.clear()
    module._commissioning_state[0] = state
    module._last_commissioning_stamp[0] = 999

    module._show_post_start_state(has_fabric=False, startup_stamp=0)

    assert module.pixel.writes[-1] == expected


def test_completion_during_start_is_published_after_node_is_started(load_main):
    boot = load_main(commissioning=[1])
    boot.module.handle_events(boot.module.node.poll())

    assert boot.module._commissioned[0] is True
    assert boot.module.endpoint.on is False
    assert boot.module.pixel.writes[-1] == boot.module.OFF_COLOR


def test_a_reopened_window_clears_a_failure(load_main):
    module = load_main().module
    module.pixel.writes.clear()

    _matter.inject_commissioning_event(2)  # SESSION FAILED
    _matter.inject_commissioning_event(3)  # WINDOW OPENED again by the package
    module.handle_events(module.node.poll())

    assert module._session_active[0] is False
    assert module.pixel.writes == [module.FAILED_COLOR, module.WINDOW_COLOR]


def test_successful_retry_after_a_failure_commissions_the_node(load_main):
    module = load_main().module
    module.pixel.writes.clear()

    _matter.inject_commissioning_event(2)  # SESSION FAILED
    _matter.inject_commissioning_event(1)  # SESSION COMPLETE
    module.handle_events(module.node.poll())

    assert module._commissioned[0] is True
    assert module.pixel.writes == [module.OFF_COLOR]


def test_closed_window_restores_commissioned_controller_state(load_main):
    module = load_main(persisted=_green_state(), fabrics=[_FABRIC]).module
    module.pixel.writes.clear()

    _matter.inject_commissioning_event(3)
    _matter.inject_commissioning_event(4)
    module.handle_events(module.node.poll())

    assert module.pixel.writes == [(0, 25, 0)]


def _green_state():
    return {
        (1, *Paths.ON_OFF): True,
        (1, *Paths.LEVEL): 25,
        (1, *Paths.HUE): 85,
        (1, *Paths.SATURATION): 254,
        (1, *Paths.COLOR_MODE): 0,
        (1, *Paths.ENHANCED_COLOR_MODE): 0,
    }


def _json_lines(output):
    """Decode every non-empty structured firmware line."""
    return [json.loads(line) for line in output.splitlines() if line]
