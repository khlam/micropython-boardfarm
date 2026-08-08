"""Stateful host fake for the native ESP-Matter MicroPython module."""

from __future__ import annotations

import errno

_EVENT_ATTRIBUTE = 0
_ORIGIN_REMOTE = 0
_ORIGIN_LOCAL = 1
_IDENTIFY_CLUSTER = 0x0003
_IDENTIFY_TIME_ATTRIBUTE = 0x0000
_ON_OFF_CLUSTER = 0x0006
_ON_OFF_ATTRIBUTE = 0x0000
_LEVEL_CONTROL_CLUSTER = 0x0008
_CURRENT_LEVEL_ATTRIBUTE = 0x0000
_COLOR_CONTROL_CLUSTER = 0x0300
_CURRENT_HUE_ATTRIBUTE = 0x0000
_CURRENT_SATURATION_ATTRIBUTE = 0x0001
_CURRENT_X_ATTRIBUTE = 0x0003
_CURRENT_Y_ATTRIBUTE = 0x0004
_COLOR_TEMPERATURE_ATTRIBUTE = 0x0007
_COLOR_MODE_ATTRIBUTE = 0x0008
_ENHANCED_COLOR_MODE_ATTRIBUTE = 0x4001

_BASE_DEFAULTS = (
    ((_IDENTIFY_CLUSTER, _IDENTIFY_TIME_ATTRIBUTE), 0),
    ((_ON_OFF_CLUSTER, _ON_OFF_ATTRIBUTE), False),
)
_DIMMABLE_DEFAULTS = (
    *_BASE_DEFAULTS,
    ((_LEVEL_CONTROL_CLUSTER, _CURRENT_LEVEL_ATTRIBUTE), 254),
)
_EXTENDED_COLOR_DEFAULTS = (
    *_DIMMABLE_DEFAULTS,
    ((_COLOR_CONTROL_CLUSTER, _CURRENT_HUE_ATTRIBUTE), 0),
    ((_COLOR_CONTROL_CLUSTER, _CURRENT_SATURATION_ATTRIBUTE), 0),
    ((_COLOR_CONTROL_CLUSTER, _CURRENT_X_ATTRIBUTE), 20494),
    ((_COLOR_CONTROL_CLUSTER, _CURRENT_Y_ATTRIBUTE), 21561),
    ((_COLOR_CONTROL_CLUSTER, _COLOR_TEMPERATURE_ATTRIBUTE), 250),
    ((_COLOR_CONTROL_CLUSTER, _COLOR_MODE_ATTRIBUTE), 2),
    ((_COLOR_CONTROL_CLUSTER, _ENHANCED_COLOR_MODE_ATTRIBUTE), 2),
)
_ENDPOINT_DEFAULTS = (
    _BASE_DEFAULTS,
    _DIMMABLE_DEFAULTS,
    _EXTENDED_COLOR_DEFAULTS,
)


class _State:
    """Mutable fake-native state kept behind one stable module object."""

    def __init__(self) -> None:
        """Allocate reusable containers before the first reset."""
        self.callback: object = None
        self.node_created = False
        self.started = False
        self.next_endpoint_id = 1
        self.endpoints: dict[int, int] = {}
        self.attributes: dict[tuple[int, int, int], object] = {}
        self.persisted: dict[tuple[int, int, int], object] = {}
        self.events: list[tuple] = []
        self.overflow = False
        self.failures: dict[str, int] = {}
        self.fabrics: list[tuple] = []
        self.commissioning_windows: list[int] = []
        self.factory_reset_requested = False


_state = _State()
commissioning_windows = _state.commissioning_windows


def reset(*, persisted: dict | None = None) -> None:
    """Reset runtime state and optionally seed the persisted attribute mirror."""
    _state.callback = None
    _state.node_created = False
    _state.started = False
    _state.next_endpoint_id = 1
    _state.endpoints.clear()
    _state.attributes.clear()
    _state.persisted.clear()
    if persisted is not None:
        _state.persisted.update(persisted)
    _state.events.clear()
    _state.overflow = False
    _state.failures.clear()
    _state.fabrics.clear()
    _state.commissioning_windows.clear()
    _state.factory_reset_requested = False


def fail_next(operation: str, error: int = errno.EIO) -> None:
    """Make the next named native operation raise ``OSError``."""
    _state.failures[operation] = error


def node_create() -> None:
    """Create the process-wide fake Matter node."""
    _raise_failure("node_create")
    if _state.node_created:
        raise OSError(errno.EALREADY, "Matter node already exists")
    _state.node_created = True


def endpoint_create(endpoint_type: int) -> int:
    """Create an endpoint and return a deterministic endpoint ID."""
    _raise_failure("endpoint_create")
    if not _state.node_created or _state.started:
        raise OSError(errno.EINVAL, "endpoint creation is not allowed")
    if not 0 <= endpoint_type < len(_ENDPOINT_DEFAULTS):
        raise OSError(errno.EINVAL, "unsupported endpoint type")
    endpoint_id = _state.next_endpoint_id
    _state.next_endpoint_id += 1
    _state.endpoints[endpoint_id] = endpoint_type
    for (cluster_id, attribute_id), value in _ENDPOINT_DEFAULTS[endpoint_type]:
        _state.attributes[(endpoint_id, cluster_id, attribute_id)] = value
    return endpoint_id


def attribute_set_initial(
    endpoint_id: int, cluster_id: int, attribute_id: int, value: object
) -> None:
    """Set an endpoint's pre-start schema default."""
    _raise_failure("attribute_set_initial")
    _require_endpoint(endpoint_id)
    if _state.started:
        raise OSError(errno.EINVAL, "initial attributes are locked")
    _state.attributes[(endpoint_id, cluster_id, attribute_id)] = value


def start() -> None:
    """Start the fake stack and restore any seeded persisted values."""
    _raise_failure("start")
    if not _state.node_created or _state.started:
        raise OSError(errno.EALREADY, "Matter stack cannot start")
    _state.attributes.update(
        {path: value for path, value in _state.persisted.items() if path[0] in _state.endpoints}
    )
    _state.started = True


def attribute_get(endpoint_id: int, cluster_id: int, attribute_id: int) -> object:
    """Read one value from the fake native mirror."""
    _raise_failure("attribute_get")
    _require_started()
    path = (endpoint_id, cluster_id, attribute_id)
    if path not in _state.attributes:
        raise OSError(errno.ENOENT, "attribute does not exist")
    return _state.attributes[path]


def attribute_publish(endpoint_id: int, cluster_id: int, attribute_id: int, value: object) -> None:
    """Publish a Python-originated value and queue its local mirror echo."""
    _raise_failure("attribute_publish")
    _set_attribute(endpoint_id, cluster_id, attribute_id, value, _ORIGIN_LOCAL)


def inject_remote_write(
    endpoint_id: int, cluster_id: int, attribute_id: int, value: object
) -> None:
    """Inject a controller write for host tests."""
    _set_attribute(endpoint_id, cluster_id, attribute_id, value, _ORIGIN_REMOTE)


def next_event() -> tuple | None:
    """Pop the oldest queued native event."""
    return _state.events.pop(0) if _state.events else None


def overflowed() -> bool:
    """Return and clear the queue-overflow indicator."""
    value = _state.overflow
    _state.overflow = False
    return value


def on_event(callback: object) -> None:
    """Record the callback representing a MicroPython scheduler wakeup."""
    if callback is not None and not callable(callback):
        raise TypeError("callback must be callable or None")
    _state.callback = callback


def open_commissioning_window(timeout_s: int) -> None:
    """Record a successfully requested commissioning window."""
    _raise_failure("open_commissioning_window")
    _require_started()
    _state.commissioning_windows.append(timeout_s)


def fabrics() -> tuple:
    """Return immutable non-secret fake fabric metadata."""
    _raise_failure("fabrics")
    _require_started()
    return tuple(_state.fabrics)


def seed_fabrics(values: list[tuple]) -> None:
    """Replace fake fabric metadata for host tests."""
    _state.fabrics[:] = values


def remove_fabric(index: int) -> None:
    """Remove a fake fabric and reopen commissioning after the last one."""
    _raise_failure("remove_fabric")
    _require_started()
    for position, fabric in enumerate(_state.fabrics):
        if fabric[0] == index:
            _state.fabrics.pop(position)
            if not _state.fabrics:
                _state.commissioning_windows.append(300)
            return
    raise OSError(errno.ENOENT, "fabric does not exist")


def factory_reset() -> None:
    """Record that the platform accepted a factory-reset request."""
    _raise_failure("factory_reset")
    _require_started()
    _state.factory_reset_requested = True


def factory_reset_was_requested() -> bool:
    """Return whether host code requested a factory reset."""
    return _state.factory_reset_requested


def _set_attribute(
    endpoint_id: int, cluster_id: int, attribute_id: int, value: object, origin: int
) -> None:
    """Update the mirror and queue one bounded attribute event."""
    _require_started()
    path = (endpoint_id, cluster_id, attribute_id)
    if path not in _state.attributes:
        raise OSError(errno.ENOENT, "attribute does not exist")
    _state.attributes[path] = value
    _state.persisted[path] = value
    event = (_EVENT_ATTRIBUTE, endpoint_id, cluster_id, attribute_id, value, origin)
    if len(_state.events) >= 32:
        _state.events.pop(0)
        _state.overflow = True
    _state.events.append(event)
    callback = _state.callback
    if callback is not None:
        callback()  # ty: ignore[call-non-callable]


def _raise_failure(operation: str) -> None:
    """Raise and consume an injected operation failure."""
    error = _state.failures.pop(operation, None)
    if error is not None:
        raise OSError(error, f"injected {operation} failure")


def _require_endpoint(endpoint_id: int) -> None:
    """Raise when an endpoint ID is unknown."""
    if endpoint_id not in _state.endpoints:
        raise OSError(errno.ENOENT, "endpoint does not exist")


def _require_started() -> None:
    """Raise when the fake stack is not running."""
    if not _state.started:
        raise OSError(errno.EINVAL, "Matter stack is not started")


reset()
