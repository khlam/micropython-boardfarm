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
    node.create_endpoint(EndpointType.ON_OFF_LIGHT)
    sleeps = []
    monkeypatch.setattr(node_module, "_RESTORE_ATTEMPTS", 2)
    monkeypatch.setattr(node_module.time, "sleep", sleeps.append)
    monkeypatch.setattr(_matter, "attribute_get", _always_fail_read)

    with pytest.raises(OSError, match="persistent read failure"):
        node.start()

    assert sleeps == [0.25]


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
    received = []
    node.on_commissioning(received.append)
    node.start()
    capsys.readouterr()

    _matter.inject_commissioning_event(state_code)

    assert received == [expected]
    assert _output(capsys) == [{"event": expected.name, "state": expected.state}]


def test_commissioning_subscription_can_be_cleared_and_validates_callback(capsys):
    node = Node()
    received = []
    node.on_commissioning(received.append)
    node.on_commissioning(None)
    with pytest.raises(TypeError, match="callable or None"):
        node.on_commissioning(42)
    node.start()
    capsys.readouterr()

    _matter.inject_commissioning_event(0)

    assert received == []
    assert _output(capsys) == [{"event": Commissioning.SESSION, "state": Commissioning.STARTED}]


def test_commissioning_callback_exception_is_contained(capsys):
    node = Node()
    calls = []

    def callback(event):
        calls.append(event.state)
        raise RuntimeError("application bug")

    node.on_commissioning(callback)
    node.start()
    capsys.readouterr()

    _matter.inject_commissioning_event(0)
    _matter.inject_commissioning_event(1)

    assert calls == [Commissioning.STARTED, Commissioning.COMPLETE]
    assert _output(capsys) == [
        {"event": Commissioning.SESSION, "state": Commissioning.STARTED},
        {
            "event": "error",
            "component": "python_callback",
            "message": "callback raised an exception",
        },
        {"event": Commissioning.SESSION, "state": Commissioning.COMPLETE},
        {
            "event": "error",
            "component": "python_callback",
            "message": "callback raised an exception",
        },
    ]


def test_invalid_native_events_are_ignored(capsys):
    node = Node()
    endpoint = node.create_endpoint(EndpointType.ON_OFF_LIGHT)
    received = []
    endpoint.on_write(received.append)
    node.start()
    capsys.readouterr()

    node._handle((0, 99, *Paths.ON_OFF, True, 0))
    node._handle((0, endpoint.id, *Paths.ON_OFF, True, 1))
    node._handle((1, 0, 0, 0, 5, 0))
    node._handle((99, 0, 0, 0, 0, 0))

    assert endpoint.on is False
    assert received == []
    assert _output(capsys) == []


def test_commissioning_queue_survives_attribute_saturation_and_preserves_order(capsys):
    node = Node()
    endpoint = node.create_endpoint(EndpointType.ON_OFF_LIGHT)
    delivery = []
    endpoint.on_write(lambda event: delivery.append(("attribute", event.value)))
    node.on_commissioning(lambda event: delivery.append(("commissioning", event.state)))
    node.start()
    capsys.readouterr()
    _matter.on_event(None)

    _matter.inject_commissioning_event(1)
    for value in range(33):
        _matter.inject_remote_write(
            endpoint.id,
            Clusters.ON_OFF,
            Attributes.ON_OFF,
            bool(value % 2),
        )

    node._drain()

    assert delivery[0] == ("commissioning", Commissioning.COMPLETE)
    assert _matter.overflow_generation() == 1
    assert _output(capsys)[0] == {
        "event": Commissioning.SESSION,
        "state": Commissioning.COMPLETE,
    }


def test_cross_kind_order_keeps_commissioning_attribute_mutation_authoritative(capsys):
    node = Node()
    endpoint = node.create_endpoint(EndpointType.ON_OFF_LIGHT)

    def complete_commissioning(event):
        if event.state == Commissioning.COMPLETE:
            endpoint.on = False

    node.on_commissioning(complete_commissioning)
    node.start()
    capsys.readouterr()
    _matter.on_event(None)

    _matter.inject_remote_write(endpoint.id, *Paths.ON_OFF, True)
    _matter.inject_commissioning_event(1)
    node._drain()

    assert endpoint.on is False
    assert _matter.attribute_get(endpoint.id, *Paths.ON_OFF) is False
    assert _output(capsys) == [{"event": Commissioning.SESSION, "state": Commissioning.COMPLETE}]


def test_overflow_resynchronizes_a_dropped_attribute_event(monkeypatch, capsys):
    node, endpoint, received = _overflowed_extended_endpoint(capsys)
    sleeps = []
    monkeypatch.setattr(node_module.time, "sleep", sleeps.append)

    node._drain()

    assert endpoint.on is True
    assert received[-1].cluster == Clusters.ON_OFF
    assert received[-1].attribute == Attributes.ON_OFF
    assert node._overflow_generation == _matter.overflow_generation() == 1
    assert sleeps == []


def test_overflow_resynchronization_retries_one_transient_read(monkeypatch, capsys):
    node, endpoint, _received = _overflowed_extended_endpoint(capsys)
    sleeps = []
    monkeypatch.setattr(node_module.time, "sleep", sleeps.append)
    _matter.fail_next("attribute_get")

    node._drain()

    assert endpoint.on is True
    assert sleeps == [0.05]
    assert node._overflow_generation == 1


def test_failed_resynchronization_remains_pending_for_later_drain(monkeypatch, capsys):
    node, endpoint, _received = _overflowed_extended_endpoint(capsys)
    original_get = _matter.attribute_get
    failing = [True]
    calls = []
    sleeps = []

    def controlled_get(*args):
        calls.append(args)
        if failing[0]:
            raise OSError("persistent read failure")
        return original_get(*args)

    monkeypatch.setattr(_matter, "attribute_get", controlled_get)
    monkeypatch.setattr(node_module.time, "sleep", sleeps.append)

    with pytest.raises(OSError, match="persistent read failure"):
        node._drain()

    assert len(calls) == 3
    assert sleeps == [0.05, 0.05]
    assert node._overflow_generation == 0
    failing[0] = False

    node._drain()

    assert endpoint.on is True
    assert node._overflow_generation == _matter.overflow_generation() == 1


def test_overflow_during_resynchronization_forces_a_second_pass(monkeypatch, capsys):
    node, endpoint, _received = _overflowed_extended_endpoint(capsys)
    native_get = _matter.attribute_get
    read_count = 0
    injected = False

    def inject_new_overflow(*path):
        nonlocal injected, read_count
        read_count += 1
        if not injected:
            injected = True
            for hue in range(33):
                _matter.inject_remote_write(endpoint.id, *Paths.HUE, hue)
        return native_get(*path)

    monkeypatch.setattr(_matter, "attribute_get", inject_new_overflow)

    node._drain()

    assert read_count == 2 * len(endpoint._state)
    assert endpoint.hue == 32
    assert node._overflow_generation == _matter.overflow_generation() == 2


def _always_fail_read(*_args):
    """Raise a persistent fake CHIP read failure."""
    raise OSError("persistent read failure")


def _overflowed_extended_endpoint(capsys):
    """Drop one unique OnOff event behind 32 queued Level events."""
    node = Node()
    endpoint = node.create_endpoint(EndpointType.EXTENDED_COLOR_LIGHT)
    received = []
    endpoint.on_write(received.append)
    node.start()
    capsys.readouterr()
    _matter.on_event(None)
    _matter.inject_remote_write(endpoint.id, *Paths.ON_OFF, True)
    for level in range(32):
        _matter.inject_remote_write(endpoint.id, *Paths.LEVEL, level)
    assert _matter.overflow_generation() == 1
    return node, endpoint, received


def _output(capsys):
    """Parse every non-empty stdout line as JSON."""
    return [json.loads(line) for line in capsys.readouterr().out.splitlines() if line]
