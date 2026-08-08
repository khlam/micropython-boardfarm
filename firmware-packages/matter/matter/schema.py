"""Attribute vocabulary and validation rules for the supported endpoints.

Pure data and pure checks. Nothing here imports ``_matter`` or touches a running
stack, so what an endpoint accepts is decided — and can be exercised — without
one.
"""

from micropython import const

__all__ = [
    "SCHEMAS",
    "Attributes",
    "Clusters",
    "ColorMode",
    "Commissioning",
    "EndpointType",
    "Origin",
    "Paths",
    "attribute_path",
    "bounded_integer",
    "default_state",
    "requested_state",
    "validate_value",
]

_TYPE_BOOL = const(0)
_TYPE_UINT8 = const(1)
_TYPE_UINT16 = const(2)


# MicroPython records const() names module-wide, including names declared in
# class bodies. These public namespaces intentionally reuse names such as
# ON_OFF, so their values must remain plain integers.
class EndpointType:
    """Endpoint schemas supported by the native ESP-Matter adapter."""

    ON_OFF_LIGHT = 0
    DIMMABLE_LIGHT = 1
    EXTENDED_COLOR_LIGHT = 2


class Clusters:
    """Matter cluster identifiers used by the supported endpoint schemas."""

    IDENTIFY = 0x0003
    ON_OFF = 0x0006
    LEVEL_CONTROL = 0x0008
    COLOR_CONTROL = 0x0300


class Attributes:
    """Matter attribute identifiers used by the supported clusters."""

    IDENTIFY_TIME = 0x0000
    ON_OFF = 0x0000
    CURRENT_LEVEL = 0x0000
    CURRENT_HUE = 0x0000
    CURRENT_SATURATION = 0x0001
    CURRENT_X = 0x0003
    CURRENT_Y = 0x0004
    COLOR_TEMPERATURE_MIREDS = 0x0007
    COLOR_MODE = 0x0008
    ENHANCED_COLOR_MODE = 0x4001


class ColorMode:
    """Color Control mode values exposed by Extended Color Light endpoints."""

    HUE_SATURATION = 0
    XY = 1
    COLOR_TEMPERATURE = 2
    ENHANCED_HUE_SATURATION = 3


class Origin:
    """Origins attached to attribute events crossing the native boundary."""

    REMOTE = "remote"
    LOCAL = "local"
    RESTORE = "restore"


class Commissioning:
    """Names and states carried by commissioning events.

    The five states are mutually distinct, so a subscriber can decide on
    ``state`` alone; ``name`` says which lifecycle the state belongs to.
    """

    SESSION = "commissioning"
    WINDOW = "commissioning_window"

    STARTED = "started"
    COMPLETE = "complete"
    FAILED = "failed"
    OPENED = "opened"
    CLOSED = "closed"


class Paths:
    """The ``(cluster, attribute)`` pair naming every mirrored attribute.

    Grouped rather than left as ten module names because they are the keys the
    schema tables, the endpoint mirror, and the named accessors all share.
    """

    IDENTIFY = (Clusters.IDENTIFY, Attributes.IDENTIFY_TIME)
    ON_OFF = (Clusters.ON_OFF, Attributes.ON_OFF)
    LEVEL = (Clusters.LEVEL_CONTROL, Attributes.CURRENT_LEVEL)
    HUE = (Clusters.COLOR_CONTROL, Attributes.CURRENT_HUE)
    SATURATION = (Clusters.COLOR_CONTROL, Attributes.CURRENT_SATURATION)
    X = (Clusters.COLOR_CONTROL, Attributes.CURRENT_X)
    Y = (Clusters.COLOR_CONTROL, Attributes.CURRENT_Y)
    TEMPERATURE = (Clusters.COLOR_CONTROL, Attributes.COLOR_TEMPERATURE_MIREDS)
    COLOR_MODE = (Clusters.COLOR_CONTROL, Attributes.COLOR_MODE)
    ENHANCED_COLOR_MODE = (Clusters.COLOR_CONTROL, Attributes.ENHANCED_COLOR_MODE)


_BASE_SCHEMA = {
    Paths.IDENTIFY: (_TYPE_UINT16, 0, 65535, 0),
    Paths.ON_OFF: (_TYPE_BOOL, 0, 1, False),
}
_DIMMABLE_SCHEMA = _BASE_SCHEMA.copy()
_DIMMABLE_SCHEMA[Paths.LEVEL] = (_TYPE_UINT8, 0, 254, 254)
_EXTENDED_COLOR_SCHEMA = _DIMMABLE_SCHEMA.copy()
_EXTENDED_COLOR_SCHEMA.update(
    {
        Paths.HUE: (_TYPE_UINT8, 0, 254, 0),
        Paths.SATURATION: (_TYPE_UINT8, 0, 254, 0),
        Paths.X: (_TYPE_UINT16, 0, 65535, 20494),
        Paths.Y: (_TYPE_UINT16, 0, 65535, 21561),
        Paths.TEMPERATURE: (_TYPE_UINT16, 153, 500, 250),
        Paths.COLOR_MODE: (_TYPE_UINT8, 0, 3, 2),
        Paths.ENHANCED_COLOR_MODE: (_TYPE_UINT8, 0, 3, 2),
    }
)
SCHEMAS = {
    EndpointType.ON_OFF_LIGHT: _BASE_SCHEMA,
    EndpointType.DIMMABLE_LIGHT: _DIMMABLE_SCHEMA,
    EndpointType.EXTENDED_COLOR_LIGHT: _EXTENDED_COLOR_SCHEMA,
}


def attribute_path(cluster: object, attribute: object) -> tuple:
    """Validate and return an integer cluster/attribute pair."""
    if not _is_plain_int(cluster):
        raise TypeError("cluster must be int")
    if not _is_plain_int(attribute):
        raise TypeError("attribute must be int")
    return (cluster, attribute)


def default_state(endpoint_type: int) -> dict:
    """Mirror the values an endpoint constructor installs for one schema."""
    return {path: definition[3] for path, definition in SCHEMAS[endpoint_type].items()}


def requested_state(endpoint_type: int, initial: dict | None) -> dict:
    """Validate a caller's initial values into normalized attribute paths."""
    if initial is None:
        return {}
    schema = SCHEMAS[endpoint_type]
    state = {}
    for path, value in initial.items():
        if not isinstance(path, tuple) or len(path) != 2:
            raise TypeError("initial keys must be (cluster, attribute) tuples")
        normalized = attribute_path(path[0], path[1])
        state[normalized] = validate_value(schema, normalized, value)
    return state


def validate_value(schema: dict, path: tuple, value: object) -> object:
    """Validate one attribute value against an endpoint schema."""
    definition = schema.get(path)
    if definition is None:
        raise ValueError("attribute is not supported by this endpoint")
    type_code, minimum, maximum, _default = definition
    if type_code == _TYPE_BOOL:
        if not isinstance(value, bool):
            raise TypeError("boolean Matter attribute requires bool")
        return value
    if not _is_plain_int(value):
        raise TypeError("integer Matter attribute requires int")
    if not minimum <= value <= maximum:
        raise ValueError(f"attribute value must be between {minimum} and {maximum}")
    return value


def bounded_integer(name: str, value: object, minimum: int, maximum: int) -> int:
    """Validate a bounded integer while excluding bool's integer subtype."""
    if not _is_plain_int(value):
        raise TypeError(f"{name} must be int")
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def _is_plain_int(value: object) -> bool:
    """Return whether a value is an int and not the bool subtype."""
    return isinstance(value, int) and not isinstance(value, bool)
