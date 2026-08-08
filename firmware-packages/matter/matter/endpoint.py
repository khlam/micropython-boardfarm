"""One native Matter endpoint and the Python copy tracking it.

A Matter *endpoint* is one addressable feature of a device (for example,
"the light's on/off switch"), identified by a ``(cluster, attribute)`` pair.
ESP-Matter (native, C++) is the authoritative store for those values; this
module keeps a plain Python dict in sync with it — called "the Python copy"
throughout this file, a separate copy living in MicroPython memory, not
shared storage. Writes that originate in Python go out to native
through :func:`_matter.attribute_publish`. Writes that originate from a
remote controller arrive as native events and come back in
through :meth:`Endpoint._accept_remote`, which is what keeps the Python copy
trustworthy without every read crossing into native code.
"""

from collections import namedtuple

import _matter

from matter.emit import error as emit_error
from matter.schema import SCHEMAS, Origin, Paths, attribute_path, validate_value

__all__ = ["Endpoint", "WriteEvent"]

# origin is always Origin.REMOTE today. It's a real field rather than a
# hardcoded constant so a callback can still branch on it if that changes.
WriteEvent = namedtuple("WriteEvent", ("endpoint_id", "cluster", "attribute", "value", "origin"))


def _attribute_property(path: tuple) -> property:
    """Build an Endpoint property that reads and publishes one attribute path.

    Declared above Endpoint because the class body evaluates these calls, so it
    cannot follow the usual private-helpers-last ordering. Naming every
    attribute kept in the Python copy is what lets application code read and
    write an endpoint without naming a cluster — or importing this package
    at all.

    Reading goes straight to the Python copy rather than through
    :meth:`Endpoint.get`. The path is a constant this module built, so
    re-checking that it holds two integers and rebuilding it as a tuple on
    every read buys nothing, and a rendering pass reads the whole endpoint
    each time a controller writes to it.

    Args:
        path: Constant ``(cluster, attribute)`` pair this property exposes.

    Returns:
        A property reading the attribute's Python copy and writing through
        :meth:`Endpoint.publish`.
    """
    cluster, attribute = path

    def read(self: "Endpoint") -> object:
        """Return this property's attribute from the Python copy."""
        try:
            return self._state[path]
        except KeyError:
            raise ValueError("attribute is not supported by this endpoint") from None

    def write(self: "Endpoint", value: object) -> None:
        """Validate and publish a new value for this property's attribute."""
        self.publish(cluster, attribute, value)

    return property(read, write)


class Endpoint:
    """Local Python copy of one native Matter endpoint's attributes.

    Every attribute an endpoint's schema tracks is also reachable by name
    (``endpoint.on``, ``endpoint.hue``, …) via the properties defined below
    with :func:`_attribute_property`, so callers never need to know a cluster
    ID to read or write one. A name the schema does not expose raises
    ``ValueError`` exactly as ``get`` and ``publish`` do, keeping an on/off
    light's ``hue`` an error rather than a silent default.
    """

    identify_time = _attribute_property(Paths.IDENTIFY)
    on = _attribute_property(Paths.ON_OFF)
    level = _attribute_property(Paths.LEVEL)
    hue = _attribute_property(Paths.HUE)
    saturation = _attribute_property(Paths.SATURATION)
    x = _attribute_property(Paths.X)
    y = _attribute_property(Paths.Y)
    temperature = _attribute_property(Paths.TEMPERATURE)
    color_mode = _attribute_property(Paths.COLOR_MODE)
    enhanced_color_mode = _attribute_property(Paths.ENHANCED_COLOR_MODE)

    def __init__(self, node: object, endpoint_id: int, endpoint_type: int, state: dict) -> None:
        """Bind a native endpoint ID to its validated Python state.

        Args:
            node: The owning :class:`matter.node.Node`, consulted for whether
                the stack has started.
            endpoint_id: The ID the native adapter assigned this endpoint.
            endpoint_type: Value from :class:`matter.schema.EndpointType`.
            state: Validated Python copy of the endpoint's attributes; this
                endpoint takes ownership of it.
        """
        self.id = endpoint_id
        self.type = endpoint_type
        self._node = node
        self._state = state
        self._schema = SCHEMAS[endpoint_type]
        self._callback = None

    def get(self, cluster: int, attribute: int) -> object:
        """Return an attribute from the Python copy, addressed by cluster and attribute ID.

        This is the general-purpose counterpart to the named properties
        (``.on``, ``.hue``, …) above: reach for it when the cluster/attribute
        pair is only known at runtime.

        Args:
            cluster: Cluster identifier from :class:`matter.schema.Clusters`.
            attribute: Attribute identifier from :class:`matter.schema.Attributes`.

        Returns:
            The current typed attribute value.

        Raises:
            ValueError: The endpoint does not expose the attribute.
        """
        path = attribute_path(cluster, attribute)
        try:
            return self._state[path]
        except KeyError:
            raise ValueError("attribute is not supported by this endpoint") from None

    def publish(self, cluster: int, attribute: int, value: object) -> None:
        """Validate a value, store it in the Python copy, then push it to ESP-Matter.

        Python is authoritative for values it sets: the Python copy keeps the new
        value even if the native publish call below fails, so application
        code can retain its decision and retry rather than silently reverting.

        Args:
            cluster: Cluster identifier from :class:`matter.schema.Clusters`.
            attribute: Attribute identifier from :class:`matter.schema.Attributes`.
            value: New value compatible with the endpoint schema.

        Raises:
            OSError: The node is not started or native publication failed.
        """
        if not self._node.started:
            raise OSError(22, "Matter node is not started")
        path = attribute_path(cluster, attribute)
        value = self._validate(path, value)
        self._state[path] = value
        _matter.attribute_publish(self.id, cluster, attribute, value)

    def on_write(self, callback: object | None) -> None:
        """Register a callback for controller-originated writes, or clear it with ``None``.

        The callback fires from :meth:`_accept_remote` — that is, only for
        writes this endpoint received from a remote controller. Writes made
        locally through :meth:`publish` never loop back through here.

        Args:
            callback: Callable receiving one immutable :class:`WriteEvent`.

        Raises:
            TypeError: The callback is neither callable nor ``None``.
        """
        if callback is not None and not callable(callback):
            raise TypeError("callback must be callable or None")
        self._callback = callback

    def _validate(self, path: tuple, value: object) -> object:
        """Validate one value against this endpoint's schema.

        Shared by :meth:`publish` and :meth:`_accept_remote` so a value is
        checked the same way regardless of whether it originated locally or
        from a remote controller.
        """
        return validate_value(self._schema, path, value)

    def _restore(self) -> None:
        """Overwrite the Python copy with whatever native currently holds.

        Called once, right after the node starts (see
        :meth:`matter.node.Node._restore_endpoints`). ESP-Matter persists
        attribute values across reboots in native storage, so a freshly built
        Python copy starts out empty of that history; this pulls it in before the
        node is exposed to controllers.
        """
        state = self._state
        for path in state:
            state[path] = _matter.attribute_get(self.id, path[0], path[1])

    def _accept_remote(self, cluster: int, attribute: int, value: object) -> None:
        """Apply one controller-originated write to the Python copy, then notify.

        Native has already accepted this value by the time it reaches here,
        so this only updates the Python copy and, if a callback is registered,
        delivers a :class:`WriteEvent`. Silently ignores an attribute this
        endpoint doesn't expose, since a caller driving this from a native
        event has no cheap way to check coverage first.
        """
        path = (cluster, attribute)
        if path not in self._state:
            return
        self._state[path] = self._validate(path, value)
        callback = self._callback
        if callback is None:
            return
        event = WriteEvent(self.id, cluster, attribute, value, Origin.REMOTE)
        try:
            callback(event)  # ty: ignore[call-top-callable]
        except Exception:  # noqa: BLE001 - user callbacks cannot stop event delivery
            emit_error("python_callback", "callback raised an exception")

    def _resynchronize(self) -> None:
        """Re-read native and dispatch only the attributes that drifted.

        Reached after the bounded event queue drops an event, so the Python copy
        may be missing a controller write it was never told about. Comparing
        against native and dispatching only the differences — via
        :meth:`_accept_remote` — means an attribute that still matches was
        never part of the gap, and doesn't generate a spurious
        :class:`WriteEvent`.
        """
        for path in tuple(self._state):
            value = _matter.attribute_get(self.id, path[0], path[1])
            if value != self._state[path]:
                self._accept_remote(path[0], path[1], value)
