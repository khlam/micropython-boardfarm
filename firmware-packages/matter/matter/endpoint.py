"""One native Matter endpoint and the Python copy tracking it.

A Matter *endpoint* is one addressable feature of a device (for example,
"the light's on/off switch"), identified by a ``(cluster, attribute)`` pair.
ESP-Matter (native, C++) is the authoritative protocol store for those values;
this module keeps a plain Python dict synchronized with it. Application writes
are explicit calls to :meth:`Endpoint.set`. Controller writes arrive
through :meth:`Endpoint._accept_remote` while
``Node.poll()`` constructs the immutable events returned to the application.
"""

from collections import namedtuple

import _matter

from matter.emit import error as emit_error
from matter.schema import SCHEMAS, Paths, attribute_path, validate_value

__all__ = ["Endpoint", "WriteEvent"]

WriteEvent = namedtuple("WriteEvent", ("endpoint", "cluster", "attribute", "value"))

_NAMED_PATHS = {
    "identify_time": Paths.IDENTIFY,
    "on": Paths.ON_OFF,
    "level": Paths.LEVEL,
    "hue": Paths.HUE,
    "saturation": Paths.SATURATION,
    "x": Paths.X,
    "y": Paths.Y,
    "temperature": Paths.TEMPERATURE,
    "color_mode": Paths.COLOR_MODE,
    "enhanced_color_mode": Paths.ENHANCED_COLOR_MODE,
    "occupancy": Paths.OCCUPANCY,
}


def _attribute_property(path: tuple) -> property:
    """Build a read-only property for one constant attribute path."""

    def read(self: "Endpoint") -> object:
        """Return this property's attribute from the Python copy."""
        return self.get(*path)

    return property(read)


class Endpoint:
    """Local Python copy of one native Matter endpoint's attributes.

    Every attribute an endpoint's schema tracks is also reachable by name
    (``endpoint.on``, ``endpoint.hue``, …) via a property installed for each
    ``_NAMED_PATHS`` entry after this class body. Properties are reads only;
    application writes go through :meth:`set`. A name the schema does not
    expose raises ``ValueError``.
    """

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

    def set(self, **attributes: object) -> None:
        """Publish a validated batch of named attributes chosen by MicroPython.

        Python is authoritative for values it sets: the Python copy keeps the
        requested batch even if native publication fails, so application code can
        retain its decision and retry rather than silently reverting. Every
        explicitly supplied value crosses the native boundary, including values
        already present in the Python state, so retrying the same call after
        ``OSError`` retries the complete decision.

        Args:
            **attributes: Named endpoint attributes and their requested values.

        Raises:
            OSError: The node is not started, or native publication failed.
            TypeError: A name is unknown or a value has the wrong Matter type.
            ValueError: No values were supplied, or the endpoint does not
                support a name or value.
        """
        if not attributes:
            raise ValueError("at least one attribute is required")
        updates = []
        for name, value in attributes.items():
            try:
                path = _NAMED_PATHS[name]
            except KeyError:
                raise TypeError(f"unknown attribute: {name}") from None
            updates.append((path[0], path[1], validate_value(self._schema, path, value)))
        # Refused before the first mirror write, so a pre-start call leaves the
        # Python copy exactly as it found it.
        if not self._node.started:
            raise OSError(22, "Matter node is not started")
        for cluster, attribute, value in updates:
            self._state[(cluster, attribute)] = value
        _matter.attributes_publish(self.id, tuple(updates))

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
            value = _matter.attribute_get(self.id, path[0], path[1])
            try:
                state[path] = validate_value(self._schema, path, value)
            except (TypeError, ValueError):
                emit_error("python_validation", "restored value rejected by schema")

    def _accept_remote(self, cluster: int, attribute: int, value: object) -> WriteEvent | None:
        """Apply one controller write and return its application event.

        Native has already accepted this value by the time it reaches here,
        so this silently ignores an attribute this endpoint doesn't expose. A
        caller driving this from a native snapshot has no cheap way to check
        coverage first.

        Args:
            cluster: Cluster identifier carried by the native record.
            attribute: Attribute identifier carried by the native record.
            value: Controller-supplied value to validate and synchronize.

        Returns:
            The immutable write event, or ``None`` when the path or value is
            outside this endpoint's schema.
        """
        path = (cluster, attribute)
        if path not in self._state:
            return None
        try:
            value = validate_value(self._schema, path, value)
        except (TypeError, ValueError):
            emit_error("python_validation", "remote value rejected by schema")
            return None
        self._state[path] = value
        return WriteEvent(self, cluster, attribute, value)


for _name, _path in _NAMED_PATHS.items():
    setattr(Endpoint, _name, _attribute_property(_path))
