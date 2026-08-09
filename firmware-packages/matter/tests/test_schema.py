"""Tests for supported Matter paths, defaults, and validation rules."""

import pytest

from matter import Attributes, Clusters, ColorMode, EndpointType
from matter.schema import (
    SCHEMAS,
    Paths,
    attribute_path,
    bounded_integer,
    default_state,
    requested_state,
    validate_value,
)


@pytest.mark.parametrize(
    "endpoint_type,expected",
    [
        (
            EndpointType.ON_OFF_LIGHT,
            {Paths.IDENTIFY: 0, Paths.ON_OFF: False},
        ),
        (
            EndpointType.DIMMABLE_LIGHT,
            {Paths.IDENTIFY: 0, Paths.ON_OFF: False, Paths.LEVEL: 254},
        ),
        (
            EndpointType.EXTENDED_COLOR_LIGHT,
            {
                Paths.IDENTIFY: 0,
                Paths.ON_OFF: False,
                Paths.LEVEL: 254,
                Paths.HUE: 0,
                Paths.SATURATION: 0,
                Paths.X: 20494,
                Paths.Y: 21561,
                Paths.TEMPERATURE: 250,
                Paths.COLOR_MODE: ColorMode.COLOR_TEMPERATURE,
                Paths.ENHANCED_COLOR_MODE: ColorMode.COLOR_TEMPERATURE,
            },
        ),
    ],
)
def test_default_state_matches_supported_endpoint_schema(endpoint_type, expected):
    assert default_state(endpoint_type) == expected


def test_public_ids_match_paths():
    assert Paths.ON_OFF == (Clusters.ON_OFF, Attributes.ON_OFF)
    assert Paths.LEVEL == (Clusters.LEVEL_CONTROL, Attributes.CURRENT_LEVEL)
    assert Paths.TEMPERATURE == (
        Clusters.COLOR_CONTROL,
        Attributes.COLOR_TEMPERATURE_MIREDS,
    )


@pytest.mark.parametrize(
    "cluster,attribute",
    [
        (True, Attributes.ON_OFF),
        (Clusters.ON_OFF, False),
        ("6", Attributes.ON_OFF),
        (Clusters.ON_OFF, None),
    ],
)
def test_attribute_path_rejects_non_plain_integers(cluster, attribute):
    with pytest.raises(TypeError):
        attribute_path(cluster, attribute)


def test_attribute_path_returns_normalized_pair():
    assert attribute_path(Clusters.ON_OFF, Attributes.ON_OFF) == Paths.ON_OFF


def test_requested_state_accepts_none_and_valid_mapping():
    assert requested_state(EndpointType.ON_OFF_LIGHT, None) == {}
    assert requested_state(
        EndpointType.EXTENDED_COLOR_LIGHT,
        {Paths.ON_OFF: True, Paths.LEVEL: 17, Paths.TEMPERATURE: 500},
    ) == {Paths.ON_OFF: True, Paths.LEVEL: 17, Paths.TEMPERATURE: 500}


@pytest.mark.parametrize("key", [1, (Clusters.ON_OFF,), (Clusters.ON_OFF, 0, 1)])
def test_requested_state_rejects_malformed_keys(key):
    with pytest.raises(TypeError, match="initial keys"):
        requested_state(EndpointType.ON_OFF_LIGHT, {key: False})


def test_requested_state_rejects_attribute_outside_schema():
    with pytest.raises(ValueError, match="not supported"):
        requested_state(EndpointType.ON_OFF_LIGHT, {Paths.LEVEL: 1})


@pytest.mark.parametrize("value", [0, 1, "true", None])
def test_boolean_attribute_requires_bool(value):
    with pytest.raises(TypeError, match="requires bool"):
        validate_value(SCHEMAS[EndpointType.ON_OFF_LIGHT], Paths.ON_OFF, value)


@pytest.mark.parametrize("value", [True, 1.5, "1", None])
def test_integer_attribute_requires_plain_int(value):
    with pytest.raises(TypeError, match="attribute value must be int"):
        validate_value(SCHEMAS[EndpointType.DIMMABLE_LIGHT], Paths.LEVEL, value)


@pytest.mark.parametrize(
    "path,minimum,maximum",
    [
        (Paths.LEVEL, 0, 254),
        (Paths.HUE, 0, 254),
        (Paths.X, 0, 65535),
        (Paths.TEMPERATURE, 153, 500),
    ],
)
def test_integer_attributes_accept_inclusive_bounds(path, minimum, maximum):
    schema = SCHEMAS[EndpointType.EXTENDED_COLOR_LIGHT]

    assert validate_value(schema, path, minimum) == minimum
    assert validate_value(schema, path, maximum) == maximum


@pytest.mark.parametrize(
    "path,value",
    [
        (Paths.LEVEL, -1),
        (Paths.LEVEL, 255),
        (Paths.X, -1),
        (Paths.X, 65536),
        (Paths.TEMPERATURE, 152),
        (Paths.TEMPERATURE, 501),
    ],
)
def test_integer_attributes_reject_values_outside_bounds(path, value):
    with pytest.raises(ValueError, match="must be between"):
        validate_value(SCHEMAS[EndpointType.EXTENDED_COLOR_LIGHT], path, value)


def test_validate_value_returns_boolean_unchanged():
    schema = SCHEMAS[EndpointType.ON_OFF_LIGHT]

    assert validate_value(schema, Paths.ON_OFF, True) is True


@pytest.mark.parametrize("value", [1, 65535])
def test_bounded_integer_accepts_inclusive_bounds(value):
    assert bounded_integer("timeout_s", value, 1, 65535) == value


@pytest.mark.parametrize("value", [True, 1.5, "1", None])
def test_bounded_integer_rejects_non_plain_integers(value):
    with pytest.raises(TypeError, match="timeout_s must be int"):
        bounded_integer("timeout_s", value, 1, 65535)


@pytest.mark.parametrize("value", [0, 65536])
def test_bounded_integer_rejects_values_outside_bounds(value):
    with pytest.raises(ValueError, match="timeout_s must be between"):
        bounded_integer("timeout_s", value, 1, 65535)
