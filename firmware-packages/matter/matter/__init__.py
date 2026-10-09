"""MicroPython API over the native ESP-Matter stack.

MicroPython owns endpoint state and application decisions. The private
``matter_native`` module owns only protocol work: endpoint schemas, the Matter
attribute mirror, commissioning, fabrics, persistence, and event transport. No
CHIP callback ever enters Python.

The API follows the Matter device model. ``Node.state`` is a
:class:`DeviceState` holding the fabric state (:class:`FabricState`) and the
network state (:class:`NetworkState`); endpoints hold application state.
``Node.poll()`` returns each change to the first as a :class:`StateEvent`, each
controller write as a :class:`WriteEvent`, and each value the schema refused as
a :class:`RejectedValue`.

The package prints nothing and claims no pin, so the application's main.py
chooses every output: :mod:`matter.emit` writes the JSON lines, and
:mod:`matter.status_led` shows ``Node.state`` on a pixel the caller passes in.
Neither is imported here.
"""

from matter.endpoint import Endpoint, RejectedValue, WriteEvent
from matter.node import Fabric, Node
from matter.schema import (
    Attributes,
    Clusters,
    ColorMode,
    EndpointType,
)
from matter.state import DeviceState, FabricState, NetworkState, StateEvent

__all__ = [
    "Attributes",
    "Clusters",
    "ColorMode",
    "DeviceState",
    "Endpoint",
    "EndpointType",
    "Fabric",
    "FabricState",
    "NetworkState",
    "Node",
    "RejectedValue",
    "StateEvent",
    "WriteEvent",
]
