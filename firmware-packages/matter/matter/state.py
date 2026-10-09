"""The device state machines: fabric membership and the network link.

A Matter device is in one fabric state (uncommissioned, commissioning, or
operational) and one network state (disconnected or connected). Its endpoints
hold the third layer, application state, which this module does not touch.

Pure data and one pure transition function. Nothing here imports
``matter_native``: the native bridge reports raw facts and :class:`matter.Node`
feeds each one through :func:`transition`.
"""

from collections import namedtuple

from micropython import const

__all__ = [
    "DeviceState",
    "FabricState",
    "NetworkState",
    "StateEvent",
    "initial_state",
    "transition",
]


class FabricState:
    """Whether the device belongs to a fabric, or is being added to one."""

    UNCOMMISSIONED = "uncommissioned"
    COMMISSIONING = "commissioning"
    OPERATIONAL = "operational"


class NetworkState:
    """Whether the Wi-Fi station link is up.

    Connected means associated with the access point. It says nothing about
    DHCP or IPv6 reachability.
    """

    DISCONNECTED = "disconnected"
    CONNECTED = "connected"


# ``window_open`` is whether a commissioning window is advertising the device
# for pairing. Uncommissioned with no window is a fault: nobody can reach it.
DeviceState = namedtuple("DeviceState", ("fabric", "network", "window_open"))

# One change of device state, from ``previous`` to ``state``. ``failed`` is True
# only on the transition that ends a failed commissioning attempt, so a
# subscriber can react to the failure once.
StateEvent = namedtuple("StateEvent", ("previous", "state", "failed"))

# Native record kinds and values. Mirrors bridge.h, which may append codes but
# never renumber them.
_KIND_COMMISSIONING = const(1)
_KIND_FABRICS = const(2)
_KIND_NETWORK = const(3)

_SESSION_STARTED = const(0)
_SESSION_COMPLETE = const(1)
_SESSION_FAILED = const(2)
_WINDOW_OPENED = const(3)
_WINDOW_CLOSED = const(4)

_NETWORK_CONNECTED = const(1)


def initial_state(fabric_count: int) -> DeviceState:
    """Return the state a freshly started node is in before any native record.

    Args:
        fabric_count: Fabrics the node restored from flash.

    Returns:
        Uncommissioned or operational, disconnected, with no window open.
    """
    return DeviceState(_resting_fabric(fabric_count), NetworkState.DISCONNECTED, False)


def transition(state: DeviceState, fabric_count: int, kind: int, value: int) -> tuple:
    """Apply one native device-state record.

    An attempt that ends without completing returns the node to whichever state
    it rested in before, so a failed second-admin pairing leaves an operational
    node operational. A record of an unknown kind changes nothing.

    Args:
        state: Current device state.
        fabric_count: Fabrics the node belongs to.
        kind: Native snapshot record kind.
        value: The record's value: a commissioning code, a fabric count, or a
            network code.

    Returns:
        ``(state, fabric_count, failed)`` after the record.
    """
    fabric, network, window_open = state
    failed = False
    if kind == _KIND_COMMISSIONING:
        if value in (_WINDOW_OPENED, _WINDOW_CLOSED):
            window_open = value == _WINDOW_OPENED
        else:
            fabric, fabric_count, failed = _end_or_start_session(value, fabric, fabric_count)
    elif kind == _KIND_FABRICS:
        fabric_count = value
        # A session in progress decides its own outcome.
        if fabric != FabricState.COMMISSIONING:
            fabric = _resting_fabric(fabric_count)
    elif kind == _KIND_NETWORK:
        connected = value == _NETWORK_CONNECTED
        network = NetworkState.CONNECTED if connected else NetworkState.DISCONNECTED
    return DeviceState(fabric, network, window_open), fabric_count, failed


def _end_or_start_session(code: int, fabric: str, fabric_count: int) -> tuple:
    """Apply one commissioning-session code.

    Args:
        code: Native session code: started, complete, or failed.
        fabric: Current fabric state.
        fabric_count: Fabrics the node belongs to.

    Returns:
        ``(fabric, fabric_count, failed)`` after the code; an unknown code
        changes nothing.
    """
    if code == _SESSION_STARTED:
        return FabricState.COMMISSIONING, fabric_count, False
    if code == _SESSION_COMPLETE:
        # Completing means the node holds a fabric, even before the fabric
        # count record that follows it arrives.
        return FabricState.OPERATIONAL, max(fabric_count, 1), False
    if code == _SESSION_FAILED:
        return _resting_fabric(fabric_count), fabric_count, True
    return fabric, fabric_count, False


def _resting_fabric(fabric_count: int) -> str:
    """Return the fabric state of a node with no commissioning session."""
    return FabricState.OPERATIONAL if fabric_count else FabricState.UNCOMMISSIONED
