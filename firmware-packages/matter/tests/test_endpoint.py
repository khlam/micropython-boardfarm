"""Integration tests for endpoint mirrors and the host native fake."""

import json

import _matter
import pytest

from matter import (
    Attributes,
    Clusters,
    ColorMode,
    EndpointType,
    Node,
    Origin,
    WriteEvent,
)


def test_named_properties_expose_each_extended_color_default():
    _node, endpoint = _endpoint(EndpointType.EXTENDED_COLOR_LIGHT)

    assert endpoint.identify_time == 0
    assert endpoint.on is False
    assert endpoint.level == 254
    assert endpoint.hue == 0
    assert endpoint.saturation == 0
    assert endpoint.x == 20494
    assert endpoint.y == 21561
    assert endpoint.temperature == 250
    assert endpoint.color_mode == ColorMode.COLOR_TEMPERATURE
    assert endpoint.enhanced_color_mode == ColorMode.COLOR_TEMPERATURE


def test_generic_get_and_named_property_reject_unsupported_attribute(capsys):
    node, endpoint = _endpoint(EndpointType.ON_OFF_LIGHT)

    assert endpoint.get(Clusters.ON_OFF, Attributes.ON_OFF) is False
    with pytest.raises(ValueError, match="not supported"):
        _ = endpoint.hue

    node.start()
    capsys.readouterr()
    with pytest.raises(ValueError, match="not supported"):
        endpoint.hue = 1
    with pytest.raises(ValueError, match="not supported"):
        endpoint.get(Clusters.LEVEL_CONTROL, Attributes.CURRENT_LEVEL)


def test_generic_get_rejects_non_integer_path_component():
    _node, endpoint = _endpoint(EndpointType.ON_OFF_LIGHT)

    with pytest.raises(TypeError, match="cluster must be int"):
        endpoint.get(True, Attributes.ON_OFF)
    with pytest.raises(TypeError, match="attribute must be int"):
        endpoint.get(Clusters.ON_OFF, False)


def test_publish_before_start_fails_without_changing_python_state():
    _node, endpoint = _endpoint(EndpointType.ON_OFF_LIGHT)

    with pytest.raises(OSError, match="not started"):
        endpoint.on = True

    assert endpoint.on is False


def test_local_publish_updates_both_mirrors_without_callback(capsys):
    node, endpoint = _endpoint(EndpointType.ON_OFF_LIGHT)
    received = []
    endpoint.on_write(received.append)
    node.start()
    capsys.readouterr()

    endpoint.on = True

    assert endpoint.on is True
    assert _matter.attribute_get(endpoint.id, Clusters.ON_OFF, Attributes.ON_OFF) is True
    assert received == []
    assert _matter.snapshot() == (0, ())


def test_failed_native_publish_retains_python_decision(capsys):
    node, endpoint = _endpoint(EndpointType.ON_OFF_LIGHT)
    node.start()
    capsys.readouterr()
    _matter.fail_next("attribute_publish")

    with pytest.raises(OSError, match="injected attribute_publish failure"):
        endpoint.on = True

    assert endpoint.on is True
    assert _matter.attribute_get(endpoint.id, Clusters.ON_OFF, Attributes.ON_OFF) is False


@pytest.mark.parametrize("value", [1, "true", None])
def test_publish_validates_attribute_value(value, capsys):
    node, endpoint = _endpoint(EndpointType.ON_OFF_LIGHT)
    node.start()
    capsys.readouterr()

    with pytest.raises(TypeError, match="requires bool"):
        endpoint.on = value


def test_remote_write_updates_mirror_and_delivers_immutable_event(capsys):
    node, endpoint = _endpoint(EndpointType.ON_OFF_LIGHT)
    received = []
    endpoint.on_write(received.append)
    node.start()
    capsys.readouterr()

    _matter.inject_remote_write(endpoint.id, Clusters.ON_OFF, Attributes.ON_OFF, True)
    node.poll()

    assert endpoint.on is True
    assert received == [
        WriteEvent(
            endpoint.id,
            Clusters.ON_OFF,
            Attributes.ON_OFF,
            True,
            Origin.REMOTE,
        )
    ]
    with pytest.raises(AttributeError):
        received[0].value = False


def test_remote_subscription_can_be_cleared(capsys):
    node, endpoint = _endpoint(EndpointType.ON_OFF_LIGHT)
    received = []
    endpoint.on_write(received.append)
    endpoint.on_write(None)
    node.start()
    capsys.readouterr()

    _matter.inject_remote_write(endpoint.id, Clusters.ON_OFF, Attributes.ON_OFF, True)
    node.poll()

    assert endpoint.on is True
    assert received == []


def test_remote_subscription_rejects_non_callable():
    _node, endpoint = _endpoint(EndpointType.ON_OFF_LIGHT)

    with pytest.raises(TypeError, match="callable or None"):
        endpoint.on_write(42)


def test_remote_callback_exception_is_json_and_delivery_continues(capsys):
    node, endpoint = _endpoint(EndpointType.ON_OFF_LIGHT)
    calls = []

    def callback(event):
        calls.append(event.value)
        raise RuntimeError("application bug")

    endpoint.on_write(callback)
    node.start()
    capsys.readouterr()

    _matter.inject_remote_write(endpoint.id, Clusters.ON_OFF, Attributes.ON_OFF, True)
    node.poll()
    _matter.inject_remote_write(endpoint.id, Clusters.ON_OFF, Attributes.ON_OFF, False)
    node.poll()

    assert calls == [True, False]
    assert endpoint.on is False
    assert _output(capsys) == [
        {
            "event": "error",
            "component": "python_callback",
            "message": "callback raised an exception",
        },
        {
            "event": "error",
            "component": "python_callback",
            "message": "callback raised an exception",
        },
    ]


def test_remote_write_outside_schema_is_reported_and_dropped(capsys):
    node, endpoint = _endpoint(EndpointType.DIMMABLE_LIGHT)
    received = []
    endpoint.on_write(received.append)
    node.start()
    capsys.readouterr()

    _matter.inject_remote_write(endpoint.id, Clusters.LEVEL_CONTROL, Attributes.CURRENT_LEVEL, 255)
    node.poll()

    assert endpoint.level == 254
    assert received == []
    assert _output(capsys) == [
        {
            "event": "error",
            "component": "python_validation",
            "message": "remote value rejected by schema",
        }
    ]

    # The rejected value did not corrupt drain state; a later, valid write
    # is still delivered normally.
    _matter.inject_remote_write(endpoint.id, Clusters.LEVEL_CONTROL, Attributes.CURRENT_LEVEL, 10)
    node.poll()

    assert endpoint.level == 10
    assert [event.value for event in received] == [10]


def test_unknown_paths_are_ignored_during_remote_accept(capsys):
    node, endpoint = _endpoint(EndpointType.ON_OFF_LIGHT)
    received = []
    endpoint.on_write(received.append)
    node.start()
    capsys.readouterr()

    endpoint._accept_remote(Clusters.LEVEL_CONTROL, Attributes.CURRENT_LEVEL, 7)

    assert endpoint.on is False
    assert received == []


def test_restore_hydrates_state_without_remote_callback(capsys):
    _matter.reset(
        persisted={(1, Clusters.ON_OFF, Attributes.ON_OFF): True},
    )
    node, endpoint = _endpoint(EndpointType.ON_OFF_LIGHT)
    received = []
    endpoint.on_write(received.append)

    node.start()

    assert endpoint.on is True
    assert received == []
    assert _output(capsys) == [{"event": "matter", "state": "ready"}]


def test_restore_of_out_of_schema_persisted_value_keeps_default(capsys):
    _matter.reset(
        persisted={(1, Clusters.LEVEL_CONTROL, Attributes.CURRENT_LEVEL): 255},
    )
    node, endpoint = _endpoint(EndpointType.DIMMABLE_LIGHT)

    node.start()

    assert endpoint.level == 254
    assert _output(capsys) == [
        {
            "event": "error",
            "component": "python_validation",
            "message": "restored value rejected by schema",
        },
        {"event": "matter", "state": "ready"},
    ]


def _endpoint(endpoint_type):
    """Create one endpoint on a fresh, unstarted node."""
    node = Node()
    return node, node.create_endpoint(endpoint_type)


def _output(capsys):
    """Parse every non-empty stdout line as JSON."""
    return [json.loads(line) for line in capsys.readouterr().out.splitlines() if line]
