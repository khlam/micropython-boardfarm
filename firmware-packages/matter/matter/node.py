"""The Matter node: one per device, owning every application endpoint."""

import time
from collections import namedtuple

import _matter
from micropython import const

from matter.emit import error as emit_error
from matter.emit import event as emit_event
from matter.endpoint import Endpoint
from matter.schema import (
    SCHEMAS,
    Commissioning,
    Paths,
    bounded_integer,
    default_state,
    requested_state,
)

__all__ = ["CommissioningEvent", "Fabric", "Node"]

CommissioningEvent = namedtuple("CommissioningEvent", ("name", "state"))
Fabric = namedtuple("Fabric", ("index", "fabric_id", "node_id", "vendor_id", "label"))

_EVENT_ATTRIBUTE = const(0)
_EVENT_COMMISSIONING = const(1)

# Native origin code for a controller-originated write. Only remote updates are
# ever queued, but the code travels with every event, so it is compared by name.
_ORIGIN_REMOTE = const(0)

# ESP-Matter's task is still bringing up Wi-Fi, BLE, and the fabric table when
# start() returns, and every attribute read is a bounded request onto that same
# task, so the first reads can expire before it services them. Together these
# give restoration roughly twenty seconds of patience.
_RESTORE_ATTEMPTS = const(40)
_RESTORE_PAUSE_S = 0.25

# Overflow recovery is shorter than startup restoration because it runs from
# the scheduler callback after the stack is already healthy. A transient CHIP
# request timeout gets two immediate retries without pinning the VM task for the
# roughly twenty seconds reserved for boot.
_RESYNCHRONIZE_ATTEMPTS = const(3)
_RESYNCHRONIZE_PAUSE_S = 0.05

# Indexed by the native commissioning state code. Built from the public
# constants so the decode table and the names subscribers compare against
# cannot drift, and pre-built so no event costs an allocation.
_COMMISSIONING_STATES = (
    CommissioningEvent(Commissioning.SESSION, Commissioning.STARTED),
    CommissioningEvent(Commissioning.SESSION, Commissioning.COMPLETE),
    CommissioningEvent(Commissioning.SESSION, Commissioning.FAILED),
    CommissioningEvent(Commissioning.WINDOW, Commissioning.OPENED),
    CommissioningEvent(Commissioning.WINDOW, Commissioning.CLOSED),
)

# A list cell rather than a bare module global so `Node.__init__` can assign
# into it without a `global` statement, while still enforcing at most one
# active node per process.
_active_node = [None]


class Node:
    """Own one Matter node and its MicroPython application endpoints."""

    def __init__(self) -> None:
        """Create the process-wide native node without starting networking."""
        if _active_node[0] is not None:
            raise OSError(114, "only one Matter node is supported")
        _matter.node_create()
        self._endpoints = {}
        self._started = False
        self._commissioning = None
        self._overflow_generation = _matter.overflow_generation()
        _active_node[0] = self

    @property
    def started(self) -> bool:
        """Return whether the native stack completed startup."""
        return self._started

    def create_endpoint(self, endpoint_type: int, initial: dict | None = None) -> Endpoint:
        """Create a supported endpoint before the Matter stack starts.

        Only the attributes ``initial`` names are written to the native store,
        because a pre-start write is persistent: it lands on the attribute the
        stack is about to restore from flash, so writing a schema default would
        discard whatever a controller last set. Every unnamed attribute keeps the
        endpoint constructor's value until :meth:`start` restores it, and Python
        mirrors the schema default until then — a placeholder, since nothing can
        be read out of the stack before it starts.

        Args:
            endpoint_type: Value from :class:`matter.schema.EndpointType`.
            initial: Optional ``(cluster, attribute)`` to value mapping. Naming
                an attribute here overrides persistence for it on every boot, so
                pass only the ones the application must pin.

        Returns:
            The new Python endpoint object.

        Raises:
            OSError: The node has already started, or a native call failed.
            TypeError: ``initial`` is not a dictionary.
            ValueError: The endpoint type, path, or value is unsupported.
        """
        if self._started:
            raise OSError(114, "endpoints must be created before Node.start")
        if endpoint_type not in SCHEMAS:
            raise ValueError("unsupported Matter endpoint type")
        if initial is not None and not isinstance(initial, dict):
            raise TypeError("initial must be a dict or None")
        requested = requested_state(endpoint_type, initial)
        state = default_state(endpoint_type)
        state.update(requested)
        endpoint_id = _matter.endpoint_create(endpoint_type)

        # Registered before the initial-attribute loop below, not after it, so
        # a raise partway through the loop still leaves this endpoint tracked.
        endpoint = Endpoint(self, endpoint_id, endpoint_type, state)
        self._endpoints[endpoint_id] = endpoint

        for (cluster, attribute), value in requested.items():
            # IdentifyTime is transient CHIP cluster state, not an application
            # default or persistent attribute. Its endpoint constructor owns
            # the required zero value until a controller starts identification.
            if (cluster, attribute) == Paths.IDENTIFY:
                continue
            _matter.attribute_set_initial(endpoint_id, cluster, attribute, value)
        return endpoint

    def start(self) -> None:
        """Start ESP-Matter, restore persisted state, and enable event delivery."""
        if self._started:
            raise OSError(114, "Matter node is already started")
        _matter.on_event(self._drain)
        _matter.start()
        self._restore_endpoints()
        self._started = True
        self._drain()
        emit_event("matter", "ready")

    def open_commissioning_window(self, timeout_s: int = 300) -> None:
        """Open a basic commissioning window for a bounded duration."""
        _require_started(self._started)
        timeout_s = bounded_integer("timeout_s", timeout_s, 1, 65535)
        _matter.open_commissioning_window(timeout_s)

    def fabrics(self) -> tuple:
        """Return non-secret metadata for every commissioned fabric."""
        _require_started(self._started)
        return tuple(Fabric(*values) for values in _matter.fabrics())

    def remove_fabric(self, index: int) -> None:
        """Remove one fabric by its operational fabric index."""
        _require_started(self._started)
        index = bounded_integer("index", index, 1, 254)
        _matter.remove_fabric(index)

    def factory_reset(self) -> None:
        """Request an ESP-Matter factory reset and platform reboot."""
        _require_started(self._started)
        _matter.factory_reset()

    def on_commissioning(self, callback: object | None) -> None:
        """Subscribe to commissioning transitions, or unsubscribe with ``None``.

        Register before :meth:`start`, which delivers whatever the stack queued
        while it was coming up. The states themselves stay reported as JSON
        whether or not anyone subscribes.

        Args:
            callback: Callable receiving one immutable
                :class:`CommissioningEvent` on the MicroPython scheduler.

        Raises:
            TypeError: The callback is neither callable nor ``None``.
        """
        if callback is not None and not callable(callback):
            raise TypeError("callback must be callable or None")
        self._commissioning = callback

    def _restore_endpoints(self) -> None:
        """Hydrate every endpoint once the freshly started stack answers reads.

        A read that expires while the stack is still starting says nothing about
        the endpoint, so it is retried rather than allowed to lose the whole
        boot. The sleep also yields to the scheduler, letting queued native
        events drain while the stack settles.

        Raises:
            OSError: The stack never answered within the restore budget.
        """
        for attempt in range(_RESTORE_ATTEMPTS):
            try:
                for endpoint in self._endpoints.values():
                    endpoint._restore()  # noqa: SLF001 - Node owns its Endpoint instances
            except OSError:
                if attempt == _RESTORE_ATTEMPTS - 1:
                    raise
                time.sleep(_RESTORE_PAUSE_S)
            else:
                return

    def _drain(self, *_args: object) -> None:
        """Drain queued native events on the MicroPython VM task."""
        while True:
            event = _matter.next_event()
            if event is None:
                break
            self._handle(event)
        self._recover_overflow()

    def _handle(self, event: tuple) -> None:
        """Route one native event without allowing it to escape the VM task."""
        kind, endpoint_id, cluster, attribute, value, origin_code = event
        if kind == _EVENT_ATTRIBUTE:
            endpoint = self._endpoints.get(endpoint_id)
            if endpoint is None or origin_code != _ORIGIN_REMOTE:
                return
            endpoint._accept_remote(  # noqa: SLF001 - Node owns callback dispatch
                cluster, attribute, value
            )
            return
        if kind == _EVENT_COMMISSIONING and 0 <= value < len(_COMMISSIONING_STATES):
            self._dispatch_commissioning(_COMMISSIONING_STATES[value])

    def _dispatch_commissioning(self, event: tuple) -> None:
        """Report one commissioning transition and hand it to the subscriber."""
        emit_event(*event)
        callback = self._commissioning
        if callback is None:
            return
        try:
            callback(event)  # ty: ignore[call-top-callable]
        except Exception:  # noqa: BLE001 - user callbacks cannot stop event delivery
            emit_error("python_callback", "callback raised an exception")

    def _resynchronize(self) -> None:
        """Recover latest remote values after the bounded queue overflows."""
        for endpoint in self._endpoints.values():
            endpoint._resynchronize()  # noqa: SLF001 - Node owns its Endpoint instances

    def _recover_overflow(self) -> None:
        """Resynchronize every unacknowledged attribute-queue generation.

        Native exposes a monotonic generation rather than a consuming flag. The
        captured generation is committed only after a complete successful pass,
        so an exception leaves the same work visible to a later drain. If CHIP
        drops another attribute while Python is reading, the outer loop observes
        the newer generation and performs one more full pass.

        Raises:
            OSError: Three consecutive resynchronization attempts failed.
        """
        while True:
            generation = _matter.overflow_generation()
            if generation == self._overflow_generation:
                return
            for attempt in range(_RESYNCHRONIZE_ATTEMPTS):
                try:
                    self._resynchronize()
                except OSError:
                    if attempt == _RESYNCHRONIZE_ATTEMPTS - 1:
                        raise
                    time.sleep(_RESYNCHRONIZE_PAUSE_S)
                else:
                    self._overflow_generation = generation
                    break


def _require_started(started: object) -> None:
    """Raise when a node administration call precedes startup."""
    if not started:
        raise OSError(22, "Matter node is not started")
