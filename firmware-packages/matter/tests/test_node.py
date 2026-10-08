"""Tests for the Matter node: lifecycle, restore, polled events, and administration."""

import errno
import time
from collections import namedtuple
from contextlib import AbstractContextManager, nullcontext
from typing import Any

import matter_native
import pytest

from matter import (
    Attributes,
    Clusters,
    Endpoint,
    EndpointType,
    Fabric,
    Node,
    WriteEvent,
)
from matter.schema import Paths
from micropython_stubs.testing import json_lines

_READY = {"event": "matter", "state": "ready"}
_RESTORED_VALUE_REJECTED = {
    "event": "error",
    "component": "python_validation",
    "message": "restored value rejected by schema",
}
_REMOTE_VALUE_REJECTED = {
    "event": "error",
    "component": "python_validation",
    "message": "remote value rejected by schema",
}

_HOME = (1, 101, 201, 301, "home")
_LAB = (2, 102, 202, 302, "lab")

# Native gives a node's first endpoint ID 1, so flash contents and controller
# writes in these tables address it by that ID.
_LIGHT_ON_OFF = (1, *Paths.ON_OFF)
_LIGHT_LEVEL = (1, *Paths.LEVEL)

_START = ("start",)

# A start() row boots a node holding one dimmable light: what flash holds for it,
# what the application pins through `initial`, and one stimulus applied just
# before start() (see _stimulate).
_Boot = namedtuple("_Boot", ("persisted", "initial", "stimulus"), defaults=(None, None, None))

# A poll() row runs on a node with one endpoint of `endpoint_type`, its native
# revision sequence starting at `generation`, started unless `started` is False.
_PollNode = namedtuple("_PollNode", ("endpoint_type", "generation", "started"), defaults=(0, True))


@pytest.mark.parametrize(
    "attempts",
    [
        pytest.param([(None, False)], id="first-node"),
        pytest.param(
            [
                (None, False),
                (None, pytest.raises(OSError, match="only one Matter node is supported")),
            ],
            id="second-node-refused",
        ),
        pytest.param(
            [
                ("node_create", pytest.raises(OSError, match="injected node_create failure")),
                (None, False),
            ],
            id="native-failure-leaves-the-node-unclaimed",
        ),
    ],
)
def test_node(attempts: list[tuple[str | None, bool | AbstractContextManager]]):
    """Node() claims the one process-wide node only once native creation succeeds.

    Args:
        attempts: Each names a native operation to fail first, then expects
            either an unstarted node (``False``) or the raise.
    """
    for native_failure, expected in attempts:
        if native_failure is not None:
            matter_native.fail_next(native_failure)
        with _outcome(expected):
            assert Node().started is expected


@pytest.mark.parametrize(
    ("before", "args", "expected", "then_write"),
    [
        pytest.param(
            [],
            (EndpointType.ON_OFF_LIGHT, None),
            {"id": 1, "type": EndpointType.ON_OFF_LIGHT, "on": False},
            None,
            id="on-off-light-without-initial",
        ),
        pytest.param([], (EndpointType.DIMMABLE_LIGHT,), {"level": 254}, None, id="dimmable-light"),
        pytest.param(
            [],
            (EndpointType.EXTENDED_COLOR_LIGHT,),
            {"temperature": 250},
            None,
            id="extended-color-light",
        ),
        pytest.param(
            [], (EndpointType.OCCUPANCY_SENSOR,), {"occupancy": 0}, None, id="occupancy-sensor"
        ),
        pytest.param(
            [],
            (
                EndpointType.EXTENDED_COLOR_LIGHT,
                {Paths.ON_OFF: True, Paths.LEVEL: 17, Paths.TEMPERATURE: 500},
            ),
            {"on": True, "level": 17, "temperature": 500},
            None,
            id="initial-mapping",
        ),
        pytest.param(
            [],
            (99,),
            pytest.raises(ValueError, match="unsupported Matter endpoint type"),
            None,
            id="unsupported-type",
        ),
        pytest.param(
            [],
            (EndpointType.ON_OFF_LIGHT, []),
            pytest.raises(TypeError, match="initial must be a dict or None"),
            None,
            id="initial-not-a-dict",
        ),
        pytest.param(
            [],
            (EndpointType.ON_OFF_LIGHT, {1: False}),
            pytest.raises(TypeError, match=r"initial keys must be \(cluster, attribute\) tuples"),
            None,
            id="key-not-a-tuple",
        ),
        pytest.param(
            [],
            (EndpointType.ON_OFF_LIGHT, {(Clusters.ON_OFF,): False}),
            pytest.raises(TypeError, match=r"initial keys must be \(cluster, attribute\) tuples"),
            None,
            id="key-too-short",
        ),
        pytest.param(
            [],
            (EndpointType.ON_OFF_LIGHT, {(Clusters.ON_OFF, Attributes.ON_OFF, 0): False}),
            pytest.raises(TypeError, match=r"initial keys must be \(cluster, attribute\) tuples"),
            None,
            id="key-too-long",
        ),
        pytest.param(
            [],
            (EndpointType.ON_OFF_LIGHT, {Paths.LEVEL: 1}),
            pytest.raises(ValueError, match="attribute is not supported by this endpoint"),
            None,
            id="path-outside-schema",
        ),
        pytest.param(
            [],
            (EndpointType.ON_OFF_LIGHT, {Paths.ON_OFF: 1}),
            pytest.raises(TypeError, match="boolean Matter attribute requires bool"),
            None,
            id="wrong-value-type",
        ),
        pytest.param(
            [],
            (EndpointType.DIMMABLE_LIGHT, {Paths.LEVEL: 255}),
            pytest.raises(ValueError, match="attribute value must be between 0 and 254"),
            None,
            id="value-out-of-range",
        ),
        pytest.param(
            [],
            (EndpointType.OCCUPANCY_SENSOR, {Paths.OCCUPANCY: 1}),
            pytest.raises(OSError, match="occupancy cannot be seeded before start"),
            None,
            id="occupancy-refuses-initial",
        ),
        pytest.param(
            [_START],
            (EndpointType.ON_OFF_LIGHT,),
            pytest.raises(OSError, match=r"endpoints must be created before Node\.start"),
            None,
            id="after-start",
        ),
        pytest.param(
            [("fail_next", "attribute_set_initial")],
            (EndpointType.ON_OFF_LIGHT, {Paths.ON_OFF: True}),
            pytest.raises(OSError, match="injected attribute_set_initial failure"),
            (*Paths.ON_OFF, True),
            id="native-refuses-initial-value-endpoint-still-routed",
        ),
    ],
)
def test_create_endpoint(
    before: list[tuple],
    args: tuple,
    expected: Any,
    then_write: tuple[int, int, object] | None,
):
    """create_endpoint() returns a validated endpoint, or raises before exposing one.

    Args:
        before: Steps run on the fresh node first (see _run).
        args: Positional arguments to create_endpoint().
        expected: Properties of the returned endpoint, or the raise.
        then_write: A controller write that poll() must still deliver to
            endpoint 1 once the node starts, although create_endpoint() raised
            after native had created it; None to skip.
    """
    node = Node()
    _run(node, None, before)

    with _outcome(expected):
        endpoint = node.create_endpoint(*args)
        assert {name: getattr(endpoint, name) for name in expected} == expected

    if then_write is not None:
        node.start()
        matter_native.inject_remote_write(1, *then_write)
        (event,) = node.poll()
        assert (event.endpoint.id, event.cluster, event.attribute, event.value) == (1, *then_write)
        assert event.endpoint.get(event.cluster, event.attribute) == event.value


@pytest.mark.parametrize(
    ("boot", "expected", "stdout"),
    [
        pytest.param(
            _Boot(),
            ({"identify_time": 0, "on": False, "level": 254}, []),
            [_READY],
            id="restores-constructor-defaults",
        ),
        pytest.param(
            _Boot(persisted={_LIGHT_ON_OFF: True}),
            ({"on": True}, []),
            [_READY],
            id="restores-persisted-value-without-event",
        ),
        pytest.param(
            _Boot(persisted={_LIGHT_LEVEL: 255}),
            ({"level": 254}, []),
            [_RESTORED_VALUE_REJECTED, _READY],
            id="out-of-schema-persisted-value-keeps-default",
        ),
        pytest.param(
            _Boot(persisted={_LIGHT_ON_OFF: False}, initial={Paths.ON_OFF: True}),
            ({"on": True}, []),
            [_READY],
            id="initial-value-overrides-persisted",
        ),
        pytest.param(
            _Boot(initial={Paths.IDENTIFY: 45}),
            ({"identify_time": 0}, []),
            [_READY],
            id="identify-initial-left-to-native-constructor",
        ),
        pytest.param(
            _Boot(persisted={_LIGHT_ON_OFF: True}, stimulus=("fail_next", "attribute_get")),
            ({"on": True}, []),
            [_READY],
            id="transient-restore-failure-retried",
        ),
        pytest.param(
            _Boot(
                persisted={_LIGHT_ON_OFF: True},
                stimulus=("write_during_start", *Paths.ON_OFF, False),
            ),
            ({"on": False}, [(*Paths.ON_OFF, False)]),
            [_READY],
            id="write-during-start-restored-then-polled",
        ),
        pytest.param(
            _Boot(stimulus=("fail_always", "attribute_get")),
            pytest.raises(OSError, match="persistent native failure"),
            [],
            id="restore-budget-exhausted",
        ),
        pytest.param(
            _Boot(stimulus=("fail_next", "start")),
            pytest.raises(OSError, match="injected start failure"),
            [],
            id="native-start-failure",
        ),
        pytest.param(
            _Boot(stimulus=_START),
            pytest.raises(OSError, match="Matter node is already started"),
            [_READY],
            id="already-started",
        ),
    ],
)
def test_start(
    boot: _Boot,
    expected: tuple[dict[str, object], list[tuple]] | AbstractContextManager,
    stdout: list[dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """start() restores every mirror before reporting ready; a failed start changes nothing.

    Args:
        boot: What flash holds, what the application pins, and the stimulus.
        expected: The light's properties after start() with the writes the first
            poll() returns, or the raise.
        stdout: Every JSON line written.
        monkeypatch: Removes the pause between restore retries, and applies
            the stimulus.
        capsys: Captures stdout.
    """
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)
    matter_native.reset(persisted=boot.persisted)
    node = Node()
    light = node.create_endpoint(EndpointType.DIMMABLE_LIGHT, boot.initial)
    _stimulate(monkeypatch, node, boot.stimulus)
    was_started = node.started

    if isinstance(expected, AbstractContextManager):
        with expected:
            node.start()
        assert node.started is was_started
    else:
        mirror, polled = expected
        node.start()
        assert node.started is True
        assert {name: getattr(light, name) for name in mirror} == mirror
        assert node.poll() == tuple(_event(light, spec) for spec in polled)
    assert json_lines(capsys.readouterr().out) == stdout


@pytest.mark.parametrize(
    ("setup", "steps", "stdout"),
    [
        pytest.param(
            _PollNode(EndpointType.ON_OFF_LIGHT, started=False),
            [("poll", pytest.raises(OSError, match="Matter node is not started"))],
            [],
            id="not-started",
        ),
        pytest.param(
            _PollNode(EndpointType.ON_OFF_LIGHT),
            [("fail_next", "snapshot"), ("poll", [])],
            [],
            id="unchanged-generation-skips-snapshot",
        ),
        pytest.param(
            _PollNode(EndpointType.ON_OFF_LIGHT),
            [("inject_remote_write", 1, *Paths.ON_OFF, True), ("poll", [(*Paths.ON_OFF, True)])],
            [],
            id="remote-write",
        ),
        pytest.param(
            _PollNode(EndpointType.OCCUPANCY_SENSOR),
            [("inject_remote_write", 1, *Paths.OCCUPANCY, 1), ("poll", [(*Paths.OCCUPANCY, 1)])],
            [],
            id="remote-occupancy-write",
        ),
        pytest.param(
            _PollNode(EndpointType.DIMMABLE_LIGHT),
            [
                ("inject_remote_write", 1, *Paths.LEVEL, 255),
                ("poll", []),
                ("mirror", *Paths.LEVEL, 254),
            ],
            [_REMOTE_VALUE_REJECTED],
            id="write-outside-schema-reported-and-omitted",
        ),
        pytest.param(
            _PollNode(EndpointType.DIMMABLE_LIGHT),
            [
                ("inject_remote_write", 1, *Paths.ON_OFF, True),
                ("inject_remote_write", 1, *Paths.ON_OFF, False),
                ("inject_remote_write", 1, *Paths.LEVEL, 10),
                ("poll", [(*Paths.ON_OFF, False), (*Paths.LEVEL, 10)]),
            ],
            [],
            id="repeated-writes-coalesce-per-path",
        ),
        pytest.param(
            _PollNode(EndpointType.ON_OFF_LIGHT),
            [
                ("inject_remote_write", 1, *Paths.ON_OFF, True),
                ("fail_next", "snapshot"),
                ("poll", pytest.raises(OSError, match="injected snapshot failure")),
                ("poll", [(*Paths.ON_OFF, True)]),
            ],
            [],
            id="snapshot-failure-then-retry-delivers",
        ),
        pytest.param(
            _PollNode(EndpointType.DIMMABLE_LIGHT),
            [
                ("inject_remote_write", 1, *Paths.ON_OFF, True),
                ("poll", [(*Paths.ON_OFF, True)]),
                ("inject_remote_write", 1, *Paths.LEVEL, 10),
                ("poll", [(*Paths.LEVEL, 10)]),
            ],
            [],
            id="delivered-write-not-redelivered",
        ),
        pytest.param(
            _PollNode(EndpointType.DIMMABLE_LIGHT, generation=0xFFFFFFFE),
            [
                ("inject_remote_write", 1, *Paths.ON_OFF, True),
                ("inject_remote_write", 1, *Paths.LEVEL, 9),
                ("poll", [(*Paths.ON_OFF, True), (*Paths.LEVEL, 9)]),
            ],
            [],
            id="revisions-wrapping-past-uint32-keep-order",
        ),
    ],
)
def test_poll(
    setup: _PollNode,
    steps: list[tuple],
    stdout: list[dict[str, str]],
    capsys: pytest.CaptureFixture[str],
):
    """poll() delivers each retained change once, in revision order, as immutable events.

    Args:
        setup: The endpoint, starting revision, and whether the node starts.
        steps: Run in order (see _run). A ``poll`` step lists the
            ``(cluster, attribute, value)`` writes it expects to the node's
            endpoint.
        stdout: Every JSON line written after start().
        capsys: Captures stdout.
    """
    matter_native.reset(generation=setup.generation)
    node = Node()
    endpoint = node.create_endpoint(setup.endpoint_type)
    if setup.started:
        node.start()
    capsys.readouterr()

    _run(node, endpoint, steps)

    assert json_lines(capsys.readouterr().out) == stdout


@pytest.mark.parametrize(
    ("before", "args", "expected"),
    [
        pytest.param(
            [_START],
            (True,),
            pytest.raises(TypeError, match="timeout_s must be int"),
            id="bool-timeout",
        ),
        pytest.param(
            [_START],
            (0,),
            pytest.raises(ValueError, match="timeout_s must be between 1 and 65535"),
            id="below-minimum-timeout",
        ),
        pytest.param(
            [_START],
            (65536,),
            pytest.raises(ValueError, match="timeout_s must be between 1 and 65535"),
            id="above-maximum-timeout",
        ),
        pytest.param(
            [],
            (),
            pytest.raises(OSError, match="Matter node is not started"),
            id="not-started",
        ),
    ],
)
def test_open_commissioning_window(
    before: list[tuple],
    args: tuple,
    expected: AbstractContextManager,
):
    """open_commissioning_window() refuses an out-of-range timeout or an unstarted node.

    Args:
        before: Steps run on the fresh node first (see _run).
        args: Positional arguments to open_commissioning_window().
        expected: The raise.
    """
    node = Node()
    _run(node, None, before)

    with expected:
        node.open_commissioning_window(*args)


@pytest.mark.parametrize(
    ("before", "expected"),
    [
        pytest.param([_START], (), id="no-fabrics"),
        pytest.param(
            [("seed_fabrics", [_HOME, _LAB]), _START],
            (Fabric(*_HOME), Fabric(*_LAB)),
            id="two-fabrics",
        ),
        pytest.param(
            [("seed_fabrics", [_HOME])],
            pytest.raises(OSError, match="Matter node is not started"),
            id="not-started",
        ),
    ],
)
def test_fabrics(before: list[tuple], expected: tuple[Fabric, ...] | AbstractContextManager):
    """fabrics() returns one Fabric record per commissioned fabric.

    Args:
        before: Steps run on the fresh node first (see _run).
        expected: The fabrics returned, or the raise.
    """
    node = Node()
    _run(node, None, before)

    with _outcome(expected):
        fabrics = node.fabrics()
        assert fabrics == expected
        assert all(type(fabric) is Fabric for fabric in fabrics)


@pytest.mark.parametrize(
    ("before", "index", "expected"),
    [
        pytest.param(
            [("seed_fabrics", [_HOME, _LAB]), _START],
            1,
            ((Fabric(*_LAB),), ()),
            id="minimum-index-one-of-two",
        ),
        pytest.param(
            [("seed_fabrics", [_HOME]), _START],
            2,
            pytest.raises(OSError, match="fabric does not exist"),
            id="unknown-fabric",
        ),
        pytest.param(
            [_START],
            True,
            pytest.raises(TypeError, match="index must be int"),
            id="bool-index",
        ),
        pytest.param(
            [_START],
            0,
            pytest.raises(ValueError, match="index must be between 1 and 254"),
            id="below-minimum-index",
        ),
        pytest.param(
            [_START],
            255,
            pytest.raises(ValueError, match="index must be between 1 and 254"),
            id="above-maximum-index",
        ),
        pytest.param(
            [("seed_fabrics", [_HOME])],
            1,
            pytest.raises(OSError, match="Matter node is not started"),
            id="not-started",
        ),
    ],
)
def test_remove_fabric(
    before: list[tuple],
    index: int,
    expected: tuple[tuple[Fabric, ...], tuple] | AbstractContextManager,
):
    """remove_fabric() drops one fabric.

    Args:
        before: Steps run on the fresh node first (see _run).
        index: The fabric index removed.
        expected: The remaining fabrics with what the next poll() returns, or
            the raise.
    """
    node = Node()
    _run(node, None, before)

    with _outcome(expected):
        node.remove_fabric(index)
        assert (node.fabrics(), node.poll()) == expected


@pytest.mark.parametrize(
    ("before", "expected"),
    [
        pytest.param([_START], None, id="started"),
        pytest.param(
            [_START, ("fail_next", "factory_reset")],
            pytest.raises(OSError, match="injected factory_reset failure"),
            id="native-failure",
        ),
        pytest.param(
            [], pytest.raises(OSError, match="Matter node is not started"), id="not-started"
        ),
    ],
)
def test_factory_reset(before: list[tuple], expected: AbstractContextManager | None):
    """factory_reset() hands the request to native and surfaces its refusal.

    Args:
        before: Steps run on the fresh node first (see _run).
        expected: None when the request is accepted, or the raise.
    """
    node = Node()
    _run(node, None, before)

    with _outcome(expected):
        assert node.factory_reset() is expected


@pytest.mark.smoke
@pytest.mark.parametrize(
    ("cluster", "attribute", "value"),
    [pytest.param(0x0006, 0x0000, True, id="on-off-cluster-on-off-attribute")],
)
def test_smoke_controller_write_turns_light_on(cluster: int, attribute: int, value: bool):
    """A controller switching the light on reaches the README "Use" loop.

    The controller writes raw IDs from the Matter Application Cluster
    Specification: the On/Off cluster is 0x0006 and its OnOff attribute 0x0000.

    Args:
        cluster: The raw cluster ID the controller writes.
        attribute: The raw attribute ID the controller writes.
        value: The value written.
    """
    node = Node()
    light = node.create_endpoint(EndpointType.ON_OFF_LIGHT)
    node.start()
    matter_native.inject_remote_write(light.id, cluster, attribute, value)

    # What the README loop hands update_hardware() for this poll.
    hardware = [
        light.on
        for event in node.poll()
        if isinstance(event, WriteEvent) and event.endpoint is light
    ]

    assert hardware == [True]


def _outcome(expected: object) -> AbstractContextManager:
    """Return the context a row's call runs in: its ``pytest.raises``, or none.

    Args:
        expected: A row's expected result or ``pytest.raises``.

    Returns:
        The ``pytest.raises``, or a context that does nothing.
    """
    return expected if isinstance(expected, AbstractContextManager) else nullcontext()


def _run(node: Node, endpoint: Endpoint | None, steps: list[tuple]):
    """Apply scenario steps in order.

    ``start`` and ``set`` drive the node and its endpoint, while ``poll`` and
    ``mirror`` assert what the application observes. Any other step calls the
    fake-native test hook it names with the remaining values.

    Args:
        node: The node under test.
        endpoint: Its endpoint, for steps that set or read one.
        steps: Each a step name followed by its values.
    """
    for name, *args in steps:
        if name == "start":
            node.start()
        elif name == "set":
            endpoint.set(**args[0])
        elif name == "poll":
            _assert_poll(node, endpoint, args[0])
        elif name == "mirror":
            cluster, attribute, value = args
            assert endpoint.get(cluster, attribute) == value
        else:
            getattr(matter_native, name)(*args)


def _assert_poll(node: Node, endpoint: Endpoint | None, expected: Any):
    """Assert poll() returns the expected events, each write applied and immutable.

    Args:
        node: The node polled.
        endpoint: The endpoint write specs refer to.
        expected: Event specs (see _event), or the raise.
    """
    with _outcome(expected):
        events = node.poll()
        assert events == tuple(_event(endpoint, spec) for spec in expected)
        for event in events:
            if isinstance(event, WriteEvent):
                assert event.endpoint.get(event.cluster, event.attribute) == event.value
                with pytest.raises(AttributeError):
                    event.value = None


def _event(endpoint: Endpoint | None, spec: tuple) -> WriteEvent:
    """Build a row's expected write event, bound to the row's endpoint.

    Args:
        endpoint: The endpoint the write spec refers to.
        spec: A ``(cluster, attribute, value)`` write.

    Returns:
        The event poll() should return for the spec.
    """
    return WriteEvent(endpoint, *spec)


def _stimulate(monkeypatch: pytest.MonkeyPatch, node: Node, stimulus: tuple | None) -> None:
    """Apply one start() stimulus, if the row has one.

    Args:
        monkeypatch: Replaces the native operation the stimulus names.
        node: The node about to start.
        stimulus: ``fail_always`` makes a native operation raise on every call,
            and ``write_during_start`` has a controller write the light while
            the native stack starts, before restore reads it back. Anything
            else is a _run step; None applies nothing.
    """
    if stimulus is None:
        return
    name, *args = stimulus
    if name == "fail_always":
        monkeypatch.setattr(matter_native, args[0], _fail_persistently)
    elif name == "write_during_start":
        native_start = matter_native.start

        def start_then_write():
            """Start the native stack, then deliver a controller write to endpoint 1."""
            native_start()
            matter_native.inject_remote_write(1, *args)

        monkeypatch.setattr(matter_native, "start", start_then_write)
    else:
        _run(node, None, [stimulus])


def _fail_persistently(*_args: object):
    """Raise a native failure that no retry outlasts.

    Args:
        *_args: The native operation's arguments, ignored.

    Raises:
        OSError: EIO, on every call.
    """
    raise OSError(errno.EIO, "persistent native failure")
