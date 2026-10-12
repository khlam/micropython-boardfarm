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
    DeviceState,
    Endpoint,
    EndpointType,
    Fabric,
    FabricState,
    NetworkState,
    Node,
    RejectedValue,
    StateEvent,
    WriteEvent,
)
from matter.schema import Paths

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

# What a successful start() leaves: the light's properties, the values start()
# returned as rejected, and the controller writes the first poll() returns. Each
# rejected value and write is a (cluster, attribute, value) triple.
_Started = namedtuple("_Started", ("mirror", "rejected", "polled"), defaults=((), ()))

# A poll() row runs on a node with one endpoint of `endpoint_type`, its native
# revision sequence starting at `generation`, started unless `started` is False.
_PollNode = namedtuple("_PollNode", ("endpoint_type", "generation", "started"), defaults=(0, True))

# A value poll() should return as rejected for the row's endpoint.
_Rejected = namedtuple("_Rejected", ("cluster", "attribute", "value"))

# Native device-state records, as callbacks.cpp retains them from CHIP events.
_SessionStarted = namedtuple("_SessionStarted", ())
_SessionComplete = namedtuple("_SessionComplete", ())
_SessionFailed = namedtuple("_SessionFailed", ())
_WindowOpened = namedtuple("_WindowOpened", ())
_WindowClosed = namedtuple("_WindowClosed", ())
_LinkUp = namedtuple("_LinkUp", ())
_LinkDown = namedtuple("_LinkDown", ())
# The node now belongs to `count` fabrics.
_FabricCount = namedtuple("_FabricCount", ("count",))

# matter_native record values (native/include/matter/bridge.h).
_COMMISSIONING_CODES = {
    _SessionStarted: 0,
    _SessionComplete: 1,
    _SessionFailed: 2,
    _WindowOpened: 3,
    _WindowClosed: 4,
}
_LINK_CODES = {_LinkDown: 0, _LinkUp: 1}

# Device states, named fabric-network-window.
_UNCOMMISSIONED_OFFLINE = DeviceState(FabricState.UNCOMMISSIONED, NetworkState.DISCONNECTED, False)
_UNCOMMISSIONED_ONLINE = DeviceState(FabricState.UNCOMMISSIONED, NetworkState.CONNECTED, False)
_UNCOMMISSIONED_PAIRABLE = DeviceState(FabricState.UNCOMMISSIONED, NetworkState.DISCONNECTED, True)
_COMMISSIONING_OFFLINE = DeviceState(FabricState.COMMISSIONING, NetworkState.DISCONNECTED, False)
_OPERATIONAL_OFFLINE = DeviceState(FabricState.OPERATIONAL, NetworkState.DISCONNECTED, False)

_DeviceCase = namedtuple("_DeviceCase", ("id", "fabrics", "records", "events", "state"))


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
    ("boot", "expected"),
    [
        pytest.param(
            _Boot(),
            _Started({"identify_time": 0, "on": False, "level": 254}),
            id="restores-constructor-defaults",
        ),
        pytest.param(
            _Boot(persisted={_LIGHT_ON_OFF: True}),
            _Started({"on": True}),
            id="restores-persisted-value-without-event",
        ),
        pytest.param(
            _Boot(persisted={_LIGHT_LEVEL: 255}),
            _Started({"level": 254}, rejected=((*Paths.LEVEL, 255),)),
            id="out-of-schema-persisted-value-keeps-default-and-is-returned",
        ),
        pytest.param(
            # The first attempt rejects the level, then times out counting fabrics.
            _Boot(persisted={_LIGHT_LEVEL: 255}, stimulus=("fail_next", "fabrics")),
            _Started({"level": 254}, rejected=((*Paths.LEVEL, 255),)),
            id="rejection-seen-before-a-retried-read-is-returned-once",
        ),
        pytest.param(
            _Boot(persisted={_LIGHT_ON_OFF: False}, initial={Paths.ON_OFF: True}),
            _Started({"on": True}),
            id="initial-value-overrides-persisted",
        ),
        pytest.param(
            _Boot(initial={Paths.IDENTIFY: 45}),
            _Started({"identify_time": 0}),
            id="identify-initial-left-to-native-constructor",
        ),
        pytest.param(
            _Boot(persisted={_LIGHT_ON_OFF: True}, stimulus=("fail_next", "attribute_get")),
            _Started({"on": True}),
            id="transient-restore-failure-retried",
        ),
        pytest.param(
            _Boot(
                persisted={_LIGHT_ON_OFF: True},
                stimulus=("write_during_start", *Paths.ON_OFF, False),
            ),
            _Started({"on": False}, polled=((*Paths.ON_OFF, False),)),
            id="write-during-start-restored-then-polled",
        ),
        pytest.param(
            _Boot(stimulus=("fail_always", "attribute_get")),
            pytest.raises(OSError, match="persistent native failure"),
            id="restore-budget-exhausted",
        ),
        pytest.param(
            _Boot(stimulus=("fail_next", "start")),
            pytest.raises(OSError, match="injected start failure"),
            id="native-start-failure",
        ),
        pytest.param(
            _Boot(stimulus=_START),
            pytest.raises(OSError, match="Matter node is already started"),
            id="already-started",
        ),
    ],
)
def test_start(
    boot: _Boot,
    expected: _Started | AbstractContextManager,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """start() restores every mirror and returns what it rejected; it prints nothing.

    A failed start changes nothing.

    Args:
        boot: What flash holds, what the application pins, and the stimulus.
        expected: What a successful start() leaves, or the raise.
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
    capsys.readouterr()

    if isinstance(expected, AbstractContextManager):
        with expected:
            node.start()
        assert node.started is was_started
    else:
        rejected = node.start()
        assert node.started is True
        assert rejected == tuple(RejectedValue(light, *spec) for spec in expected.rejected)
        assert {name: getattr(light, name) for name in expected.mirror} == expected.mirror
        assert node.poll() == tuple(_event(light, spec) for spec in expected.polled)
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize(
    ("setup", "steps"),
    [
        pytest.param(
            _PollNode(EndpointType.ON_OFF_LIGHT, started=False),
            [("poll", pytest.raises(OSError, match="Matter node is not started"))],
            id="not-started",
        ),
        pytest.param(
            _PollNode(EndpointType.ON_OFF_LIGHT),
            [("fail_next", "snapshot"), ("poll", [])],
            id="unchanged-generation-skips-snapshot",
        ),
        pytest.param(
            _PollNode(EndpointType.ON_OFF_LIGHT),
            [("inject_remote_write", 1, *Paths.ON_OFF, True), ("poll", [(*Paths.ON_OFF, True)])],
            id="remote-write",
        ),
        pytest.param(
            _PollNode(EndpointType.OCCUPANCY_SENSOR),
            [("inject_remote_write", 1, *Paths.OCCUPANCY, 1), ("poll", [(*Paths.OCCUPANCY, 1)])],
            id="remote-occupancy-write",
        ),
        pytest.param(
            _PollNode(EndpointType.DIMMABLE_LIGHT),
            [
                ("inject_remote_write", 1, *Paths.LEVEL, 255),
                ("poll", [_Rejected(*Paths.LEVEL, 255)]),
                ("mirror", *Paths.LEVEL, 254),
            ],
            id="write-outside-schema-returned-as-rejected-and-omitted",
        ),
        pytest.param(
            _PollNode(EndpointType.DIMMABLE_LIGHT),
            [
                ("inject_remote_write", 1, *Paths.ON_OFF, True),
                ("inject_remote_write", 1, *Paths.ON_OFF, False),
                ("inject_remote_write", 1, *Paths.LEVEL, 10),
                ("poll", [(*Paths.ON_OFF, False), (*Paths.LEVEL, 10)]),
            ],
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
            id="delivered-write-not-redelivered",
        ),
        pytest.param(
            _PollNode(EndpointType.DIMMABLE_LIGHT, generation=0xFFFFFFFE),
            [
                ("inject_remote_write", 1, *Paths.ON_OFF, True),
                ("inject_remote_write", 1, *Paths.LEVEL, 9),
                ("poll", [(*Paths.ON_OFF, True), (*Paths.LEVEL, 9)]),
            ],
            id="revisions-wrapping-past-uint32-keep-order",
        ),
    ],
)
def test_poll(setup: _PollNode, steps: list[tuple], capsys: pytest.CaptureFixture[str]):
    """poll() delivers each retained change once, in revision order, as immutable events.

    It prints nothing.

    Args:
        setup: The endpoint, starting revision, and whether the node starts.
        steps: Run in order (see _run). A ``poll`` step lists the events it
            expects for the node's endpoint: a ``(cluster, attribute, value)``
            write, or a ``_Rejected`` value.
        capsys: Captures stdout.
    """
    matter_native.reset(generation=setup.generation)
    node = Node()
    endpoint = node.create_endpoint(setup.endpoint_type)
    if setup.started:
        node.start()
    capsys.readouterr()

    _run(node, endpoint, steps)

    assert capsys.readouterr().out == ""


@pytest.mark.parametrize(
    "case",
    [
        _DeviceCase(
            id="no-fabric-restored-starts-uncommissioned",
            fabrics=0,
            records=(),
            events=(),
            state=_UNCOMMISSIONED_OFFLINE,
        ),
        _DeviceCase(
            id="fabric-restored-starts-operational",
            fabrics=1,
            records=(),
            events=(),
            state=_OPERATIONAL_OFFLINE,
        ),
        _DeviceCase(
            id="uncommissioned-session-started-is-commissioning",
            fabrics=0,
            records=(_SessionStarted(),),
            events=(StateEvent(_UNCOMMISSIONED_OFFLINE, _COMMISSIONING_OFFLINE, False),),
            state=_COMMISSIONING_OFFLINE,
        ),
        _DeviceCase(
            id="operational-another-controller-pairs-is-commissioning",
            fabrics=1,
            records=(_SessionStarted(),),
            events=(StateEvent(_OPERATIONAL_OFFLINE, _COMMISSIONING_OFFLINE, False),),
            state=_COMMISSIONING_OFFLINE,
        ),
        _DeviceCase(
            # The fabric count arrives first and changes nothing: the session decides.
            id="commissioning-session-complete-is-operational",
            fabrics=0,
            records=(_SessionStarted(), _FabricCount(1), _SessionComplete()),
            events=(
                StateEvent(_UNCOMMISSIONED_OFFLINE, _COMMISSIONING_OFFLINE, False),
                StateEvent(_COMMISSIONING_OFFLINE, _OPERATIONAL_OFFLINE, False),
            ),
            state=_OPERATIONAL_OFFLINE,
        ),
        _DeviceCase(
            id="commissioning-attempt-failed-with-no-fabric-is-uncommissioned",
            fabrics=0,
            records=(_SessionStarted(), _SessionFailed()),
            events=(
                StateEvent(_UNCOMMISSIONED_OFFLINE, _COMMISSIONING_OFFLINE, False),
                StateEvent(_COMMISSIONING_OFFLINE, _UNCOMMISSIONED_OFFLINE, True),
            ),
            state=_UNCOMMISSIONED_OFFLINE,
        ),
        _DeviceCase(
            id="commissioning-attempt-failed-with-a-fabric-held-is-operational",
            fabrics=1,
            records=(_SessionStarted(), _SessionFailed()),
            events=(
                StateEvent(_OPERATIONAL_OFFLINE, _COMMISSIONING_OFFLINE, False),
                StateEvent(_COMMISSIONING_OFFLINE, _OPERATIONAL_OFFLINE, True),
            ),
            state=_OPERATIONAL_OFFLINE,
        ),
        _DeviceCase(
            # Not an edge: the attempt fails, but the state it rests in is unchanged.
            id="uncommissioned-attempt-failed-reports-the-failure-alone",
            fabrics=0,
            records=(_SessionFailed(),),
            events=(StateEvent(_UNCOMMISSIONED_OFFLINE, _UNCOMMISSIONED_OFFLINE, True),),
            state=_UNCOMMISSIONED_OFFLINE,
        ),
        _DeviceCase(
            id="operational-last-fabric-removed-is-uncommissioned",
            fabrics=1,
            records=(_FabricCount(0),),
            events=(StateEvent(_OPERATIONAL_OFFLINE, _UNCOMMISSIONED_OFFLINE, False),),
            state=_UNCOMMISSIONED_OFFLINE,
        ),
        _DeviceCase(
            id="operational-second-fabric-added-stays-operational",
            fabrics=1,
            records=(_FabricCount(2),),
            events=(),
            state=_OPERATIONAL_OFFLINE,
        ),
        _DeviceCase(
            id="disconnected-link-up-is-connected-and-a-restated-link-changes-nothing",
            fabrics=0,
            records=(_LinkUp(), _LinkUp()),
            events=(StateEvent(_UNCOMMISSIONED_OFFLINE, _UNCOMMISSIONED_ONLINE, False),),
            state=_UNCOMMISSIONED_ONLINE,
        ),
        _DeviceCase(
            id="connected-link-lost-is-disconnected",
            fabrics=0,
            records=(_LinkUp(), _LinkDown()),
            events=(
                StateEvent(_UNCOMMISSIONED_OFFLINE, _UNCOMMISSIONED_ONLINE, False),
                StateEvent(_UNCOMMISSIONED_ONLINE, _UNCOMMISSIONED_OFFLINE, False),
            ),
            state=_UNCOMMISSIONED_OFFLINE,
        ),
        _DeviceCase(
            id="window-opened-then-closed",
            fabrics=0,
            records=(_WindowOpened(), _WindowClosed()),
            events=(
                StateEvent(_UNCOMMISSIONED_OFFLINE, _UNCOMMISSIONED_PAIRABLE, False),
                StateEvent(_UNCOMMISSIONED_PAIRABLE, _UNCOMMISSIONED_OFFLINE, False),
            ),
            state=_UNCOMMISSIONED_OFFLINE,
        ),
    ],
    ids=lambda case: case.id,
)
def test_poll_device_state(case: _DeviceCase, capsys: pytest.CaptureFixture[str]):
    """poll() follows the README's fabric and network diagrams, one StateEvent per change.

    Each record reaches native, then the node polls. It prints nothing.

    Args:
        case: Fabrics restored at start, the records in order, every event the
            polls return, and the device state after the last poll.
        capsys: Captures stdout.
    """
    matter_native.seed_fabrics([_HOME, _LAB][: case.fabrics])
    node = Node()
    node.start()
    capsys.readouterr()

    events = []
    for record in case.records:
        _send_record(record)
        events.extend(node.poll())

    assert tuple(events) == case.events
    assert node.state == case.state
    assert capsys.readouterr().out == ""


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

    ``start`` starts the node, while ``poll`` and ``mirror`` assert what the
    application observes. Any other step calls the fake-native test hook it
    names with the remaining values.

    Args:
        node: The node under test.
        endpoint: Its endpoint, for steps that read one.
        steps: Each a step name followed by its values.
    """
    for name, *args in steps:
        if name == "start":
            node.start()
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


def _event(endpoint: Endpoint | None, spec: tuple) -> WriteEvent | RejectedValue:
    """Build a row's expected endpoint event, bound to the row's endpoint.

    Args:
        endpoint: The endpoint the spec refers to.
        spec: A ``(cluster, attribute, value)`` write, or a ``_Rejected`` value.

    Returns:
        The event poll() should return for the spec.
    """
    if isinstance(spec, _Rejected):
        return RejectedValue(endpoint, *spec)
    return WriteEvent(endpoint, *spec)


def _send_record(record: tuple) -> None:
    """Retain one device-state record in native, as callbacks.cpp does.

    Args:
        record: A commissioning, link, or fabric-count record.
    """
    kind = type(record)
    if kind in _COMMISSIONING_CODES:
        matter_native.inject_commissioning_event(_COMMISSIONING_CODES[kind])
    elif kind in _LINK_CODES:
        matter_native.inject_network_event(_LINK_CODES[kind])
    else:
        matter_native.seed_fabrics([_HOME, _LAB][: record.count])
        matter_native.inject_fabric_count()


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
