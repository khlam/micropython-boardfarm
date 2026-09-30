"""Unit and fuzz tests for an endpoint's named properties, get(), and set()."""

import contextlib
import errno
import random
from collections import namedtuple
from collections.abc import Callable

import matter_native
import pytest

from matter import Attributes, Clusters, ColorMode, Endpoint, EndpointType, Node, WriteEvent

_ENDPOINT_TYPES = (
    EndpointType.ON_OFF_LIGHT,
    EndpointType.DIMMABLE_LIGHT,
    EndpointType.EXTENDED_COLOR_LIGHT,
    EndpointType.OCCUPANCY_SENSOR,
)

# Every named property and the (cluster, attribute) path it reads.
_PATHS = {
    "identify_time": (Clusters.IDENTIFY, Attributes.IDENTIFY_TIME),
    "on": (Clusters.ON_OFF, Attributes.ON_OFF),
    "level": (Clusters.LEVEL_CONTROL, Attributes.CURRENT_LEVEL),
    "hue": (Clusters.COLOR_CONTROL, Attributes.CURRENT_HUE),
    "saturation": (Clusters.COLOR_CONTROL, Attributes.CURRENT_SATURATION),
    "x": (Clusters.COLOR_CONTROL, Attributes.CURRENT_X),
    "y": (Clusters.COLOR_CONTROL, Attributes.CURRENT_Y),
    "temperature": (Clusters.COLOR_CONTROL, Attributes.COLOR_TEMPERATURE_MIREDS),
    "color_mode": (Clusters.COLOR_CONTROL, Attributes.COLOR_MODE),
    "enhanced_color_mode": (Clusters.COLOR_CONTROL, Attributes.ENHANCED_COLOR_MODE),
    "occupancy": (Clusters.OCCUPANCY_SENSING, Attributes.OCCUPANCY),
}

_NOT_SUPPORTED = ValueError("attribute is not supported by this endpoint")
_REQUIRES_BOOL = TypeError("boolean Matter attribute requires bool")
_REQUIRES_INT = TypeError("attribute value must be int")
_OUTSIDE_0_1 = ValueError("attribute value must be between 0 and 1")
_OUTSIDE_0_254 = ValueError("attribute value must be between 0 and 254")
_OUTSIDE_0_65535 = ValueError("attribute value must be between 0 and 65535")
_OUTSIDE_153_500 = ValueError("attribute value must be between 153 and 500")
_NOT_STARTED = OSError(errno.EINVAL, "Matter node is not started")
_PUBLISH_FAILURE = OSError(errno.EIO, "injected attributes_publish failure")

_BATCH = {"on": True, "hue": 42, "saturation": 200}
# Controller writes left pending in native on every path of _BATCH.
_REMOTE = {"on": False, "hue": 7, "saturation": 9}

# One set() scenario. `remote` is injected as pending controller writes before
# the call; `fail_publish` makes the first native publication fail; `outcomes`
# is the result of each consecutive identical call (None: it returned);
# `mirrored` holds the properties that differ afterwards; `delivered` holds the
# controller writes the next poll() returns, in the order they were injected.
_SetCase = namedtuple(
    "_SetCase",
    (
        "scenario",
        "endpoint_type",
        "attributes",
        "started",
        "remote",
        "fail_publish",
        "outcomes",
        "mirrored",
        "delivered",
    ),
    defaults=(True, {}, False, (None,), {}, {}),
)

_FUZZ = random.Random(0x5E7_0A77)  # noqa: S311 - seeded for reproducible inputs, not secrecy
_FUZZ_NAMES = (*_PATHS, "brightness")
# Each integer range's edges and one step past them, then the wrong types.
_EDGE_INTEGERS = (-1, 0, 1, 2, 3, 4, 152, 153, 254, 255, 500, 501, 65535, 65536)
_FUZZ_VALUES = (*_EDGE_INTEGERS, False, True, 1.5, "1", None)
_FUZZ_RUNS = [
    [
        (
            _FUZZ.choice(_ENDPOINT_TYPES),
            _FUZZ.choice(_FUZZ_NAMES),
            _FUZZ.choice((*_FUZZ_VALUES, _FUZZ.randint(-1, 65536))),
        )
        for _draw in range(30)
    ]
    for _run in range(20)
]


@pytest.mark.parametrize(
    ("endpoint_type", "name", "expected"),
    [
        (EndpointType.ON_OFF_LIGHT, "identify_time", 0),
        (EndpointType.ON_OFF_LIGHT, "on", False),
        (EndpointType.DIMMABLE_LIGHT, "identify_time", 0),
        (EndpointType.DIMMABLE_LIGHT, "on", False),
        (EndpointType.DIMMABLE_LIGHT, "level", 254),
        (EndpointType.EXTENDED_COLOR_LIGHT, "identify_time", 0),
        (EndpointType.EXTENDED_COLOR_LIGHT, "on", False),
        (EndpointType.EXTENDED_COLOR_LIGHT, "level", 254),
        (EndpointType.EXTENDED_COLOR_LIGHT, "hue", 0),
        (EndpointType.EXTENDED_COLOR_LIGHT, "saturation", 0),
        (EndpointType.EXTENDED_COLOR_LIGHT, "x", 20494),
        (EndpointType.EXTENDED_COLOR_LIGHT, "y", 21561),
        (EndpointType.EXTENDED_COLOR_LIGHT, "temperature", 250),
        (EndpointType.EXTENDED_COLOR_LIGHT, "color_mode", ColorMode.COLOR_TEMPERATURE),
        (EndpointType.EXTENDED_COLOR_LIGHT, "enhanced_color_mode", ColorMode.COLOR_TEMPERATURE),
        (EndpointType.OCCUPANCY_SENSOR, "identify_time", 0),
        (EndpointType.OCCUPANCY_SENSOR, "occupancy", 0),
        (EndpointType.ON_OFF_LIGHT, "hue", _NOT_SUPPORTED),
        (EndpointType.OCCUPANCY_SENSOR, "on", _NOT_SUPPORTED),
    ],
)
def test_named_property_reads_schema_default_and_is_read_only(
    endpoint_type: int, name: str, expected: object
):
    """A named property reads its schema default and refuses assignment.

    Args:
        endpoint_type: The kind of endpoint created.
        name: The property read.
        expected: Its default, or the exception an unsupported property raises.
    """
    _node, endpoint = _endpoint(endpoint_type)

    # The interpreter words this message, differently on MicroPython, so only
    # the type is the package's contract.
    with pytest.raises(AttributeError) as caught:
        setattr(endpoint, name, 1)
    assert caught.type is AttributeError
    _assert_outcome(lambda: getattr(endpoint, name), expected)


@pytest.mark.parametrize(
    ("cluster", "attribute", "expected"),
    [
        (Clusters.ON_OFF, Attributes.ON_OFF, False),
        (Clusters.LEVEL_CONTROL, Attributes.CURRENT_LEVEL, _NOT_SUPPORTED),
        (True, Attributes.ON_OFF, TypeError("cluster must be int")),
        ("6", Attributes.ON_OFF, TypeError("cluster must be int")),
        (Clusters.ON_OFF, False, TypeError("attribute must be int")),
        (Clusters.ON_OFF, None, TypeError("attribute must be int")),
    ],
)
def test_get_reads_attribute_by_path(cluster: object, attribute: object, expected: object):
    """get() reads a supported attribute by path and rejects unsupported or non-int paths.

    Args:
        cluster: The cluster ID passed to get().
        attribute: The attribute ID passed to get().
        expected: The value read, or the exception get() raises.
    """
    _node, endpoint = _endpoint(EndpointType.ON_OFF_LIGHT)

    _assert_outcome(lambda: endpoint.get(cluster, attribute), expected)


@pytest.mark.parametrize(
    "case",
    [
        _SetCase(
            "republishes-mirrored-value-over-older-remote-write",
            EndpointType.ON_OFF_LIGHT,
            {"on": False},
            remote={"on": True},
            mirrored={"on": False},
        ),
        _SetCase(
            "native-failure-keeps-batch-and-leaves-remote-writes-pending",
            EndpointType.EXTENDED_COLOR_LIGHT,
            _BATCH,
            remote=_REMOTE,
            fail_publish=True,
            outcomes=(_PUBLISH_FAILURE,),
            mirrored=_BATCH,
            delivered=_REMOTE,
        ),
        _SetCase(
            "retry-after-native-failure-publishes-whole-batch",
            EndpointType.EXTENDED_COLOR_LIGHT,
            _BATCH,
            remote=_REMOTE,
            fail_publish=True,
            outcomes=(_PUBLISH_FAILURE, None),
            mirrored=_BATCH,
        ),
        _SetCase(
            "before-start",
            EndpointType.ON_OFF_LIGHT,
            {"on": True},
            started=False,
            outcomes=(_NOT_STARTED,),
        ),
        _SetCase(
            "validation-precedes-start-check",
            EndpointType.DIMMABLE_LIGHT,
            {"on": True, "level": 255},
            started=False,
            outcomes=(_OUTSIDE_0_254,),
        ),
        _SetCase(
            "empty-batch",
            EndpointType.ON_OFF_LIGHT,
            {},
            outcomes=(ValueError("at least one attribute is required"),),
        ),
        _SetCase(
            "unknown-name",
            EndpointType.ON_OFF_LIGHT,
            {"brightness": 1},
            outcomes=(TypeError("unknown attribute: brightness"),),
        ),
        _SetCase(
            "name-outside-schema", EndpointType.ON_OFF_LIGHT, {"hue": 1}, outcomes=(_NOT_SUPPORTED,)
        ),
        _SetCase(
            "one-bad-value-among-good-ones",
            EndpointType.EXTENDED_COLOR_LIGHT,
            {"on": True, "hue": 255, "saturation": 200},
            remote=_REMOTE,
            outcomes=(_OUTSIDE_0_254,),
            delivered=_REMOTE,
        ),
        _SetCase(
            "bool-rejects-0", EndpointType.ON_OFF_LIGHT, {"on": 0}, outcomes=(_REQUIRES_BOOL,)
        ),
        _SetCase(
            "bool-rejects-1", EndpointType.ON_OFF_LIGHT, {"on": 1}, outcomes=(_REQUIRES_BOOL,)
        ),
        _SetCase(
            "bool-rejects-str",
            EndpointType.ON_OFF_LIGHT,
            {"on": "true"},
            outcomes=(_REQUIRES_BOOL,),
        ),
        _SetCase(
            "bool-rejects-none", EndpointType.ON_OFF_LIGHT, {"on": None}, outcomes=(_REQUIRES_BOOL,)
        ),
        _SetCase(
            "int-rejects-bool",
            EndpointType.DIMMABLE_LIGHT,
            {"level": True},
            outcomes=(_REQUIRES_INT,),
        ),
        _SetCase(
            "int-rejects-float",
            EndpointType.DIMMABLE_LIGHT,
            {"level": 1.5},
            outcomes=(_REQUIRES_INT,),
        ),
        _SetCase(
            "int-rejects-str",
            EndpointType.DIMMABLE_LIGHT,
            {"level": "1"},
            outcomes=(_REQUIRES_INT,),
        ),
        _SetCase(
            "int-rejects-none",
            EndpointType.DIMMABLE_LIGHT,
            {"level": None},
            outcomes=(_REQUIRES_INT,),
        ),
        _SetCase(
            "level-accepts-0", EndpointType.DIMMABLE_LIGHT, {"level": 0}, mirrored={"level": 0}
        ),
        _SetCase(
            "level-accepts-254",
            EndpointType.DIMMABLE_LIGHT,
            {"level": 254},
            mirrored={"level": 254},
        ),
        _SetCase(
            "level-rejects-minus-1",
            EndpointType.DIMMABLE_LIGHT,
            {"level": -1},
            outcomes=(_OUTSIDE_0_254,),
        ),
        _SetCase(
            "level-rejects-255",
            EndpointType.DIMMABLE_LIGHT,
            {"level": 255},
            outcomes=(_OUTSIDE_0_254,),
        ),
        _SetCase(
            "hue-accepts-0", EndpointType.EXTENDED_COLOR_LIGHT, {"hue": 0}, mirrored={"hue": 0}
        ),
        _SetCase(
            "hue-accepts-254",
            EndpointType.EXTENDED_COLOR_LIGHT,
            {"hue": 254},
            mirrored={"hue": 254},
        ),
        _SetCase(
            "hue-rejects-minus-1",
            EndpointType.EXTENDED_COLOR_LIGHT,
            {"hue": -1},
            outcomes=(_OUTSIDE_0_254,),
        ),
        _SetCase(
            "hue-rejects-255",
            EndpointType.EXTENDED_COLOR_LIGHT,
            {"hue": 255},
            outcomes=(_OUTSIDE_0_254,),
        ),
        _SetCase("x-accepts-0", EndpointType.EXTENDED_COLOR_LIGHT, {"x": 0}, mirrored={"x": 0}),
        _SetCase(
            "x-accepts-65535",
            EndpointType.EXTENDED_COLOR_LIGHT,
            {"x": 65535},
            mirrored={"x": 65535},
        ),
        _SetCase(
            "x-rejects-minus-1",
            EndpointType.EXTENDED_COLOR_LIGHT,
            {"x": -1},
            outcomes=(_OUTSIDE_0_65535,),
        ),
        _SetCase(
            "x-rejects-65536",
            EndpointType.EXTENDED_COLOR_LIGHT,
            {"x": 65536},
            outcomes=(_OUTSIDE_0_65535,),
        ),
        _SetCase(
            "temperature-accepts-153",
            EndpointType.EXTENDED_COLOR_LIGHT,
            {"temperature": 153},
            mirrored={"temperature": 153},
        ),
        _SetCase(
            "temperature-accepts-500",
            EndpointType.EXTENDED_COLOR_LIGHT,
            {"temperature": 500},
            mirrored={"temperature": 500},
        ),
        _SetCase(
            "temperature-rejects-152",
            EndpointType.EXTENDED_COLOR_LIGHT,
            {"temperature": 152},
            outcomes=(_OUTSIDE_153_500,),
        ),
        _SetCase(
            "temperature-rejects-501",
            EndpointType.EXTENDED_COLOR_LIGHT,
            {"temperature": 501},
            outcomes=(_OUTSIDE_153_500,),
        ),
        _SetCase(
            "occupancy-accepts-0",
            EndpointType.OCCUPANCY_SENSOR,
            {"occupancy": 0},
            mirrored={"occupancy": 0},
        ),
        _SetCase(
            "occupancy-accepts-1",
            EndpointType.OCCUPANCY_SENSOR,
            {"occupancy": 1},
            mirrored={"occupancy": 1},
        ),
        _SetCase(
            "occupancy-rejects-bool",
            EndpointType.OCCUPANCY_SENSOR,
            {"occupancy": True},
            outcomes=(_REQUIRES_INT,),
        ),
        _SetCase(
            "occupancy-rejects-2",
            EndpointType.OCCUPANCY_SENSOR,
            {"occupancy": 2},
            outcomes=(_OUTSIDE_0_1,),
        ),
    ],
    ids=lambda case: case.scenario,
)
def test_set_validates_mirrors_and_publishes_batch(case: _SetCase):
    """set() validates the whole batch before mirroring and publishing any of it.

    Args:
        case: One set() scenario; see ``_SetCase``.
    """
    node, endpoint = _endpoint(case.endpoint_type)
    if case.started:
        node.start()
    for name, value in case.remote.items():
        matter_native.inject_remote_write(endpoint.id, *_PATHS[name], value)
    if case.fail_publish:
        matter_native.fail_next("attributes_publish")
    before = _properties(endpoint)

    for outcome in case.outcomes:
        _assert_outcome(lambda: endpoint.set(**case.attributes), outcome)

    assert _properties(endpoint) == {**before, **case.mirrored}
    # An unstarted node cannot poll; its rows inject no controller writes.
    if case.started:
        assert node.poll() == tuple(
            WriteEvent(endpoint, *_PATHS[name], value) for name, value in case.delivered.items()
        )


@pytest.mark.fuzz
@pytest.mark.parametrize("draws", _FUZZ_RUNS)
def test_fuzz_set_reads_back_or_changes_nothing(draws: list[tuple[int, str, object]]):
    """Each set() either reads back exactly or is rejected and changes no endpoint.

    Args:
        draws: Random (endpoint type, property name, value) writes, applied in order.
    """
    node = Node()
    endpoints = {kind: node.create_endpoint(kind) for kind in _ENDPOINT_TYPES}
    node.start()

    for endpoint_type, name, value in draws:
        target = endpoints[endpoint_type]
        expected = {kind: _properties(endpoint) for kind, endpoint in endpoints.items()}
        try:
            target.set(**{name: value})
        except (TypeError, ValueError):
            pass  # the documented rejections; any other exception fails the test
        else:
            read = getattr(target, name)
            assert (type(read), read) == (type(value), value)
            expected[endpoint_type][name] = value

        assert {kind: _properties(endpoint) for kind, endpoint in endpoints.items()} == expected


def _endpoint(endpoint_type: int) -> tuple[Node, Endpoint]:
    """Create one endpoint on a fresh, unstarted node.

    Args:
        endpoint_type: The kind of endpoint to create.

    Returns:
        The node and its endpoint.
    """
    node = Node()
    return node, node.create_endpoint(endpoint_type)


def _properties(endpoint: Endpoint) -> dict[str, object]:
    """Return every named property the endpoint exposes, keyed by name.

    Args:
        endpoint: The endpoint to read.

    Returns:
        Each supported property's current value.
    """
    values = {}
    for name in _PATHS:
        with contextlib.suppress(ValueError):
            values[name] = getattr(endpoint, name)
    return values


def _assert_outcome(call: Callable[[], object], expected: object) -> None:
    """Assert that ``call()`` returns ``expected`` exactly, or raises exactly it.

    Args:
        call: Zero-argument callable exercising the entry point.
        expected: The value the call returns, compared together with its type,
            or an exception whose exact type and message the call raises.
    """
    if isinstance(expected, Exception):
        with pytest.raises(type(expected)) as caught:
            call()
        assert (type(caught.value), str(caught.value)) == (type(expected), str(expected))
    else:
        result = call()
        assert (type(result), result) == (type(expected), expected)
