"""Integration tests for Matter node lifecycle, routing, and recovery."""

import json

import _matter
import pytest

import matter.node as node_module
from matter import (
    Attributes,
    Clusters,
    Commissioning,
    CommissioningEvent,
    EndpointType,
    Fabric,
    Node,
    WriteEvent,
)
from matter.schema import Paths


def test_node_enforces_process_wide_singleton():
    Node()

    with pytest.raises(OSError, match="only one Matter node"):
        Node()


def test_failed_native_node_creation_does_not_claim_singleton():
    _matter.fail_next("node_create")

    with pytest.raises(OSError, match="injected node_create failure"):
        Node()

    assert isinstance(Node(), Node)


def test_create_endpoint_assigns_stable_ids_and_defaults():
    node = Node()

    switch = node.create_endpoint(EndpointType.ON_OFF_LIGHT)
    dimmer = node.create_endpoint(EndpointType.DIMMABLE_LIGHT)
    color = node.create_endpoint(EndpointType.EXTENDED_COLOR_LIGHT)

    assert (switch.id, dimmer.id, color.id) == (1, 2, 3)
    assert switch.on is False
    assert dimmer.level == 254
    assert color.temperature == 250


def test_create_endpoint_validates_type_and_initial_mapping():
    node = Node()

    with pytest.raises(ValueError, match="unsupported Matter endpoint type"):
        node.create_endpoint(99)
    with pytest.raises(TypeError, match="initial must be a dict or None"):
        node.create_endpoint(EndpointType.ON_OFF_LIGHT, initial=[])


def test_create_endpoint_tracks_native_endpoint_despite_initial_attribute_failure():
    node = Node()
    _matter.fail_next("attribute_set_initial")

    with pytest.raises(OSError, match="injected attribute_set_initial failure"):
        node.create_endpoint(EndpointType.ON_OFF_LIGHT, initial={Paths.ON_OFF: True})

    endpoint = node._endpoints[1]
    event = node._handle((1, 0, 1, *Paths.ON_OFF, False))

    assert event.value is False
    assert event.endpoint is endpoint
    assert endpoint.on is False


def test_create_endpoint_is_forbidden_after_start(capsys):
    node = Node()
    node.start()
    capsys.readouterr()

    with pytest.raises(OSError, match=r"before Node\.start"):
        node.create_endpoint(EndpointType.ON_OFF_LIGHT)


def test_requested_initial_value_overrides_seeded_persistence(capsys):
    _matter.reset(
        persisted={(1, Clusters.ON_OFF, Attributes.ON_OFF): False},
    )
    node = Node()
    endpoint = node.create_endpoint(
        EndpointType.ON_OFF_LIGHT,
        initial={Paths.ON_OFF: True},
    )

    node.start()

    assert endpoint.on is True
    assert _matter.attribute_get(endpoint.id, *Paths.ON_OFF) is True
    assert _output(capsys) == [{"event": "matter", "state": "ready"}]


def test_identify_initial_value_is_left_to_native_constructor(capsys):
    node = Node()
    endpoint = node.create_endpoint(
        EndpointType.ON_OFF_LIGHT,
        initial={Paths.IDENTIFY: 45},
    )
    assert endpoint.identify_time == 45

    node.start()

    assert endpoint.identify_time == 0
    assert _matter.attribute_get(endpoint.id, *Paths.IDENTIFY) == 0
    assert _output(capsys) == [{"event": "matter", "state": "ready"}]


def test_start_retries_transient_restore_failure(monkeypatch, capsys):
    node = Node()
    node.create_endpoint(EndpointType.ON_OFF_LIGHT)
    sleeps = []
    monkeypatch.setattr(node_module.time, "sleep", sleeps.append)
    _matter.fail_next("attribute_get")

    node.start()

    assert node.started is True
    assert sleeps == [0.25]
    assert _output(capsys) == [{"event": "matter", "state": "ready"}]


def test_start_raises_after_restore_retry_budget(monkeypatch):
    node = Node()
    endpoint = node.create_endpoint(EndpointType.ON_OFF_LIGHT)
    sleeps = []
    monkeypatch.setattr(node_module, "_RESTORE_ATTEMPTS", 2)
    monkeypatch.setattr(node_module.time, "sleep", sleeps.append)
    monkeypatch.setattr(_matter, "attribute_get", _always_fail_read)

    with pytest.raises(OSError, match="persistent read failure"):
        node.start()

    assert sleeps == [0.25]
    assert node.started is False
    with pytest.raises(OSError, match="not started"):
        endpoint.set(on=True)


def test_node_cannot_start_twice(capsys):
    node = Node()
    node.start()
    capsys.readouterr()

    with pytest.raises(OSError, match="already started"):
        node.start()


@pytest.mark.parametrize(
    "method,args",
    [
        ("open_commissioning_window", ()),
        ("fabrics", ()),
        ("remove_fabric", (1,)),
        ("factory_reset", ()),
        ("poll", ()),
    ],
)
def test_administration_requires_started_node(method, args):
    node = Node()

    with pytest.raises(OSError, match="not started"):
        getattr(node, method)(*args)


def test_commissioning_window_validates_and_forwards_timeout(capsys):
    node = Node()
    node.start()
    capsys.readouterr()

    node.open_commissioning_window()
    node.open_commissioning_window(1)
    node.open_commissioning_window(65535)

    assert _matter.commissioning_windows == [300, 1, 65535]


@pytest.mark.parametrize("timeout", [True, 0, 65536])
def test_commissioning_window_rejects_invalid_timeout(timeout, capsys):
    node = Node()
    node.start()
    capsys.readouterr()

    with pytest.raises((TypeError, ValueError)):
        node.open_commissioning_window(timeout)


def test_fabric_snapshot_and_removal(capsys):
    first = (1, 101, 201, 301, "home")
    second = (2, 102, 202, 302, "lab")
    _matter.seed_fabrics([first, second])
    node = Node()
    node.start()
    capsys.readouterr()

    assert node.fabrics() == (Fabric(*first), Fabric(*second))
    node.remove_fabric(1)
    assert node.fabrics() == (Fabric(*second),)
    node.remove_fabric(2)
    assert node.fabrics() == ()
    assert _matter.commissioning_windows == [300]
    with pytest.raises(OSError, match="fabric does not exist"):
        node.remove_fabric(2)


@pytest.mark.parametrize("index", [True, 0, 255])
def test_remove_fabric_rejects_invalid_index(index, capsys):
    node = Node()
    node.start()
    capsys.readouterr()

    with pytest.raises((TypeError, ValueError)):
        node.remove_fabric(index)


def test_factory_reset_is_forwarded(capsys):
    node = Node()
    node.start()
    capsys.readouterr()

    node.factory_reset()

    assert _matter.factory_reset_was_requested() is True


@pytest.mark.parametrize(
    "state_code,expected",
    [
        (0, CommissioningEvent(Commissioning.SESSION, Commissioning.STARTED)),
        (1, CommissioningEvent(Commissioning.SESSION, Commissioning.COMPLETE)),
        (2, CommissioningEvent(Commissioning.SESSION, Commissioning.FAILED)),
        (3, CommissioningEvent(Commissioning.WINDOW, Commissioning.OPENED)),
        (4, CommissioningEvent(Commissioning.WINDOW, Commissioning.CLOSED)),
    ],
)
def test_commissioning_event_is_reported_and_delivered(state_code, expected, capsys):
    node = Node()
    node.start()
    capsys.readouterr()

    _matter.inject_commissioning_event(state_code)
    events = node.poll()

    assert events == (expected,)
    assert _output(capsys) == [{"event": expected.name, "state": expected.state}]


def test_unchanged_generation_skips_snapshot(monkeypatch, capsys):
    node = Node()
    node.start()
    capsys.readouterr()
    calls = []
    monkeypatch.setattr(_matter, "snapshot", lambda: calls.append(True))

    events = node.poll()

    assert calls == []
    assert events == ()


def test_repeated_writes_coalesce_and_attributes_remain_independent(capsys):
    node = Node()
    endpoint = node.create_endpoint(EndpointType.DIMMABLE_LIGHT)
    node.start()
    capsys.readouterr()

    _matter.inject_remote_write(endpoint.id, *Paths.ON_OFF, True)
    _matter.inject_remote_write(endpoint.id, *Paths.ON_OFF, False)
    _matter.inject_remote_write(endpoint.id, *Paths.LEVEL, 10)
    events = node.poll()

    assert [(event.cluster, event.value) for event in events] == [
        (Clusters.ON_OFF, False),
        (Clusters.LEVEL_CONTROL, 10),
    ]
    assert all(event.endpoint is endpoint for event in events)


def test_snapshot_failure_retries_without_committing_generation(capsys):
    node = Node()
    endpoint = node.create_endpoint(EndpointType.ON_OFF_LIGHT)
    node.start()
    capsys.readouterr()
    _matter.inject_remote_write(endpoint.id, *Paths.ON_OFF, True)
    _matter.fail_next("snapshot")

    with pytest.raises(OSError, match="injected snapshot failure"):
        node.poll()
    assert node._generation == 0

    events = node.poll()

    assert [event.value for event in events] == [True]
    assert endpoint.on is True
    assert node._generation == _matter.generation()


def test_local_publish_discards_older_pending_remote_write(capsys):
    node = Node()
    endpoint = node.create_endpoint(EndpointType.ON_OFF_LIGHT)
    node.start()
    capsys.readouterr()
    _matter.inject_remote_write(endpoint.id, *Paths.ON_OFF, True)

    endpoint.set(on=False)
    events = node.poll()

    assert endpoint.on is False
    assert events == ()


def test_cross_kind_revision_order_keeps_newer_mutation_authoritative(capsys):
    node = Node()
    endpoint = node.create_endpoint(EndpointType.ON_OFF_LIGHT)

    node.start()
    capsys.readouterr()
    _matter.inject_remote_write(endpoint.id, *Paths.ON_OFF, True)
    _matter.inject_commissioning_event(1)

    events = node.poll()
    for event in events:
        if isinstance(event, CommissioningEvent) and event.state == Commissioning.COMPLETE:
            endpoint.set(on=False)

    assert [type(event) for event in events] == [WriteEvent, CommissioningEvent]
    assert endpoint.on is False
    assert _matter.attribute_get(endpoint.id, *Paths.ON_OFF) is False


def test_commissioning_session_and_window_replay_in_revision_order(capsys):
    node = Node()
    node.start()
    capsys.readouterr()
    _matter.inject_commissioning_event(2)
    _matter.inject_commissioning_event(3)

    events = node.poll()

    assert [event.state for event in events] == [Commissioning.FAILED, Commissioning.OPENED]


def test_startup_restore_precedes_first_polled_write(capsys, monkeypatch):
    _matter.reset(persisted={(1, *Paths.ON_OFF): True})
    node = Node()
    endpoint = node.create_endpoint(EndpointType.ON_OFF_LIGHT)
    native_start = _matter.start

    def start_with_write():
        native_start()
        _matter.inject_remote_write(endpoint.id, *Paths.ON_OFF, False)

    monkeypatch.setattr(_matter, "start", start_with_write)
    node.start()

    assert endpoint.on is False
    events = node.poll()
    assert [event.value for event in events] == [False]


def test_wrapping_revisions_are_ordered_from_committed_generation(capsys):
    node = Node()
    endpoint = node.create_endpoint(EndpointType.DIMMABLE_LIGHT)
    node.start()
    capsys.readouterr()
    node._generation = 0xFFFFFFFE
    _matter._state.generation = 0xFFFFFFFE
    _matter.inject_remote_write(endpoint.id, *Paths.ON_OFF, True)
    _matter.inject_remote_write(endpoint.id, *Paths.LEVEL, 9)

    events = node.poll()

    assert [event.value for event in events] == [True, 9]


def _always_fail_read(*_args):
    """Raise a persistent fake CHIP read failure."""
    raise OSError("persistent read failure")


def _output(capsys):
    """Parse every non-empty stdout line as JSON."""
    return [json.loads(line) for line in capsys.readouterr().out.splitlines() if line]
