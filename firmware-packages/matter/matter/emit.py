"""The JSON lines a Matter application writes over serial.

Nothing in this package calls these; the application's main.py does, at the
place each line is chosen.
"""

import ujson

from matter.state import StateEvent


def emit(obj: dict) -> None:
    """Write one compact JSON object followed by a newline."""
    print(ujson.dumps(obj))  # noqa: T201 - the JSON writer is the one stdout boundary


def error(component: str, message: str) -> None:
    """Report a recoverable fault without interrupting event delivery."""
    emit({"event": "error", "component": component, "message": message})


def emit_state(event: StateEvent) -> None:
    """Report one change of device state: a failed attempt, then each changed field.

    Writes ``{"event":"commissioning","state":"failed"}`` for a failed attempt,
    then one line each for a changed fabric state, network state, and
    commissioning window, in that order.

    Args:
        event: A :class:`matter.StateEvent` from :meth:`matter.Node.poll`.
    """
    previous, state, failed = event
    if failed:
        emit({"event": "commissioning", "state": "failed"})
    if state.fabric != previous.fabric:
        emit({"event": "fabric", "state": state.fabric})
    if state.network != previous.network:
        emit({"event": "network", "state": state.network})
    if state.window_open != previous.window_open:
        window = "opened" if state.window_open else "closed"
        emit({"event": "commissioning_window", "state": window})
