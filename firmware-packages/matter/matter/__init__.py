"""Reusable MicroPython application API over native ESP-Matter stack.

MicroPython owns endpoint state and application decisions. The private
``_matter`` module owns only protocol work: endpoint schemas, the Matter
attribute mirror, commissioning, fabrics, persistence, and event transport.

This split keeps CHIP's C++ stack, task model, and threading rules fully
contained behind the native bridge, so application code never touches a CHIP
task or interrupt directly and can't violate its concurrency assumptions.
Application logic stays in MicroPython where it's easy to iterate on and
test on the host, while the parts that must match ESP-Matter's C++ ABI stay
narrow, native, and isolated from product-specific changes.

"""

from matter.endpoint import Endpoint, WriteEvent
from matter.node import CommissioningEvent, Fabric, Node
from matter.schema import (
    Attributes,
    Clusters,
    ColorMode,
    Commissioning,
    EndpointType,
    Origin,
    Paths,
)

__all__ = [
    "Attributes",
    "Clusters",
    "ColorMode",
    "Commissioning",
    "CommissioningEvent",
    "Endpoint",
    "EndpointType",
    "Fabric",
    "Node",
    "Origin",
    "Paths",
    "WriteEvent",
]
