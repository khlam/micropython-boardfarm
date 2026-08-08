"""Single JSON writer for lifecycle events and recoverable Matter errors."""

import ujson


def emit(obj: dict) -> None:
    """Write one compact JSON object followed by a newline."""
    print(ujson.dumps(obj))  # noqa: T201 - the JSON writer is the one stdout boundary


def event(name: str, state: str) -> None:
    """Report a named lifecycle transition, e.g. commissioning -> complete."""
    emit({"event": name, "state": state})


def error(component: str, message: str) -> None:
    """Report a recoverable fault without interrupting event delivery."""
    emit({"event": "error", "component": component, "message": message})
