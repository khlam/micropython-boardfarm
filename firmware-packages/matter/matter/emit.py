"""Single JSON writer for lifecycle events and recoverable Matter errors."""

import ujson

# Extra destinations for the same lines stdout gets. A list rather than a single
# slot so a caller can add one without knowing whether another already exists,
# and module-level so every emit() in the package feeds them without threading a
# writer object through Node and Endpoint.
_sinks = []


def add_sink(sink: object) -> None:
    """Deliver every emitted line to ``sink`` as well as to stdout.

    The serial console is not the only place this stream can usefully go — a
    project may also be publishing it over the network. Registering a sink keeps
    one writer building the JSON instead of a second ``print`` elsewhere drifting
    out of step with this one.

    Args:
        sink: Callable taking the encoded line. It must neither raise nor block:
            emit() runs on the MicroPython scheduler as well as on the
            application's tasks, so a sink that does either stalls event
            delivery. Buffer and return.
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
