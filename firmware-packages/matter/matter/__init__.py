"""Reusable MicroPython application API over native ESP-Matter stack.

MicroPython owns endpoint state and application decisions. The private
``matter_native`` module owns only protocol work: endpoint schemas, the Matter
attribute mirror, commissioning, fabrics, persistence, and event transport.

The API follows the Matter device model. ``Node.state`` is a
:class:`DeviceState` holding the fabric state (:class:`FabricState`) and the
network state (:class:`NetworkState`); endpoints hold application state.
``Node.poll()`` reports changes to the first as :class:`StateEvent` and to the
second as :class:`WriteEvent`.

:mod:`matter.status_led` shows ``Node.state`` on a status pixel. It is not
imported here, so ``import matter`` loads no pixel driver.

This split keeps CHIP's C++ stack, task model, and threading rules fully
contained behind the native bridge, so application code never touches a CHIP
task or interrupt directly and can't violate its concurrency assumptions.
Application logic stays in MicroPython where it's easy to iterate on and
test on the host, while the parts that must match ESP-Matter's C++ ABI stay
narrow, native, and isolated from product-specific changes.

"""

from matter.endpoint import Endpoint, WriteEvent
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
    "StateEvent",
    "WriteEvent",
]
