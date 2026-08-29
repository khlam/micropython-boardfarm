"""Integration tests for explicit endpoint state and publication."""

import _matter
import pytest

from matter import Attributes, Clusters, ColorMode, EndpointType, Node, WriteEvent
from micropython_stubs.testing import json_lines


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


def test_named_properties_are_read_only():
    _node, endpoint = _endpoint(EndpointType.ON_OFF_LIGHT)

    with pytest.raises(AttributeError):
        endpoint.on = True


def test_generic_get_and_named_property_reject_unsupported_attribute():
    _node, endpoint = _endpoint(EndpointType.ON_OFF_LIGHT)

    assert endpoint.get(Clusters.ON_OFF, Attributes.ON_OFF) is False
    with pytest.raises(ValueError, match="not supported"):
        _ = endpoint.hue
    with pytest.raises(ValueError, match="not supported"):
        endpoint.get(Clusters.LEVEL_CONTROL, Attributes.CURRENT_LEVEL)


def test_generic_get_rejects_non_integer_path_component():
    _node, endpoint = _endpoint(EndpointType.ON_OFF_LIGHT)

    with pytest.raises(TypeError, match="cluster must be int"):
        endpoint.get(True, Attributes.ON_OFF)
    with pytest.raises(TypeError, match="attribute must be int"):
        endpoint.get(Clusters.ON_OFF, False)


def test_set_before_start_fails_without_changing_python_state():
    _node, endpoint = _endpoint(EndpointType.ON_OFF_LIGHT)

    with pytest.raises(OSError, match="not started"):
        endpoint.set(on=True)

    assert endpoint.on is False


def test_set_publishes_one_named_batch(monkeypatch):
    node, endpoint = _endpoint(EndpointType.EXTENDED_COLOR_LIGHT)
    node.start()
    batches = []
    native_publish = _matter.attributes_publish

    def record(endpoint_id, updates):
        batches.append((endpoint_id, updates))
        native_publish(endpoint_id, updates)

    monkeypatch.setattr(_matter, "attributes_publish", record)

    endpoint.set(on=True, hue=42, saturation=200)

    assert batches == [
        (
            endpoint.id,
            (
                (Clusters.ON_OFF, Attributes.ON_OFF, True),
                (Clusters.COLOR_CONTROL, Attributes.CURRENT_HUE, 42),
                (Clusters.COLOR_CONTROL, Attributes.CURRENT_SATURATION, 200),
            ),
        )
    ]
    assert (endpoint.on, endpoint.hue, endpoint.saturation) == (True, 42, 200)


def test_set_republishes_explicit_values_that_already_match(monkeypatch):
    node, endpoint = _endpoint(EndpointType.ON_OFF_LIGHT)
    node.start()
    calls = []
    native_publish = _matter.attributes_publish

    def record(endpoint_id, updates):
        calls.append(updates)
        native_publish(endpoint_id, updates)

    monkeypatch.setattr(_matter, "attributes_publish", record)

    endpoint.set(on=False)
    endpoint.set(on=False)

    assert calls == [
        ((Clusters.ON_OFF, Attributes.ON_OFF, False),),
        ((Clusters.ON_OFF, Attributes.ON_OFF, False),),
    ]


def test_set_validates_whole_batch_before_changing_state(monkeypatch):
    node, endpoint = _endpoint(EndpointType.EXTENDED_COLOR_LIGHT)
    node.start()
    calls = []
    monkeypatch.setattr(_matter, "attributes_publish", lambda *_args: calls.append(True))

    with pytest.raises(ValueError, match="between 0 and 254"):
        endpoint.set(on=True, hue=255)

    assert endpoint.on is False
    assert endpoint.hue == 0
    assert calls == []


@pytest.mark.parametrize(
    ("attributes", "exception", "message"),
    [
        ({}, ValueError, "at least one"),
        ({"missing": 1}, TypeError, "unknown attribute"),
        ({"hue": 1}, ValueError, "not supported"),
        ({"on": 1}, TypeError, "requires bool"),
    ],
)
def test_set_rejects_invalid_named_batches(attributes, exception, message):
    _node, endpoint = _endpoint(EndpointType.ON_OFF_LIGHT)

    with pytest.raises(exception, match=message):
        endpoint.set(**attributes)


def test_failed_batch_keeps_requested_state_and_full_retry(monkeypatch):
    node, endpoint = _endpoint(EndpointType.EXTENDED_COLOR_LIGHT)
    node.start()
    requested = {"on": True, "hue": 42, "saturation": 200}
    _matter.fail_next("attributes_publish")

    with pytest.raises(OSError, match="injected attributes_publish failure"):
        endpoint.set(**requested)

    assert (endpoint.on, endpoint.hue, endpoint.saturation) == (True, 42, 200)
    assert _matter.attribute_get(endpoint.id, Clusters.ON_OFF, Attributes.ON_OFF) is False

    calls = []
    native_publish = _matter.attributes_publish

    def record(endpoint_id, updates):
        calls.append(updates)
        native_publish(endpoint_id, updates)

    monkeypatch.setattr(_matter, "attributes_publish", record)
    endpoint.set(**requested)

    assert len(calls) == 1
    assert len(calls[0]) == 3
    assert _matter.attribute_get(endpoint.id, Clusters.ON_OFF, Attributes.ON_OFF) is True


def test_remote_write_updates_mirror_and_poll_returns_immutable_event():
    node, endpoint = _endpoint(EndpointType.ON_OFF_LIGHT)
    node.start()

    _matter.inject_remote_write(endpoint.id, Clusters.ON_OFF, Attributes.ON_OFF, True)
    events = node.poll()

    assert endpoint.on is True
    assert events == (WriteEvent(endpoint, Clusters.ON_OFF, Attributes.ON_OFF, True),)
    with pytest.raises(AttributeError):
        events[0].value = False


def test_remote_write_outside_schema_is_reported_and_omitted(capsys):
    node, endpoint = _endpoint(EndpointType.DIMMABLE_LIGHT)
    node.start()
    capsys.readouterr()

    _matter.inject_remote_write(endpoint.id, Clusters.LEVEL_CONTROL, Attributes.CURRENT_LEVEL, 255)

    assert node.poll() == ()
    assert endpoint.level == 254
    assert _output(capsys) == [
        {
            "event": "error",
            "component": "python_validation",
            "message": "remote value rejected by schema",
        }
    ]


def test_unknown_paths_are_ignored_during_remote_accept():
    _node, endpoint = _endpoint(EndpointType.ON_OFF_LIGHT)

    event = endpoint._accept_remote(Clusters.LEVEL_CONTROL, Attributes.CURRENT_LEVEL, 7)

    assert event is None
    assert endpoint.on is False


def test_restore_hydrates_state_without_an_event(capsys):
    _matter.reset(persisted={(1, Clusters.ON_OFF, Attributes.ON_OFF): True})
    node, endpoint = _endpoint(EndpointType.ON_OFF_LIGHT)

    node.start()

    assert endpoint.on is True
    assert node.poll() == ()
    assert _output(capsys) == [{"event": "matter", "state": "ready"}]


def test_restore_of_out_of_schema_persisted_value_keeps_default(capsys):
    _matter.reset(persisted={(1, Clusters.LEVEL_CONTROL, Attributes.CURRENT_LEVEL): 255})
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
    return json_lines(capsys.readouterr().out)
