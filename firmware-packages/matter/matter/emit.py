"""Single JSON writer for lifecycle events and recoverable Matter errors."""

import ujson

_sinks = []


def add_sink(sink: object) -> None:
    """Deliver each stdout JSON line to an additional destination.

    Args:
        sink: Callable accepting the encoded line without a trailing newline.
            It runs synchronously and must neither raise nor block.
    """
    _sinks.append(sink)


def emit(obj: dict) -> None:
    """Write one compact JSON object followed by a newline."""
    line = ujson.dumps(obj)
    print(line)  # noqa: T201 - the JSON writer is the one stdout boundary
    for sink in _sinks:
        sink(line)


def event(name: str, state: str) -> None:
    """Report a named lifecycle transition, e.g. commissioning -> complete."""
    emit({"event": name, "state": state})


def error(component: str, message: str) -> None:
    """Report a recoverable fault without interrupting event delivery."""
    emit({"event": "error", "component": component, "message": message})
