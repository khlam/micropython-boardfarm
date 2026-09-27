"""Tests for the Matter facade's single JSON stdout boundary."""

from collections.abc import Callable
from functools import partial

import pytest

from matter.emit import add_sink, emit, error, event
from micropython_stubs.testing import json_lines


@pytest.mark.parametrize(
    "obj",
    [
        pytest.param({"answer": 42, "ok": True}, id="flat_scalars"),
        pytest.param({}, id="empty_object"),
        pytest.param(
            {"t": 1200, "targets": [{"slot": 0, "x_mm": -350, "y_mm": 1200, "speed_cm_s": 0}]},
            id="nested_containers",
        ),
        pytest.param(
            {"diag": "matter_poll_err", "err": "first line\nsecond line"},
            id="newline_inside_string",
        ),
    ],
)
def test_emit_writes_one_json_line(capsys, obj):
    emit(obj)

    out = capsys.readouterr().out
    assert out.count("\n") == 1
    assert out.endswith("\n")
    assert json_lines(out) == [obj]


@pytest.mark.parametrize(
    ("name", "state", "expected"),
    [("matter", "ready", {"event": "matter", "state": "ready"})],
)
def test_event_writes_named_transition(capsys, name, state, expected):
    event(name, state)

    assert json_lines(capsys.readouterr().out) == [expected]


@pytest.mark.parametrize(
    ("component", "message", "expected"),
    [
        (
            "python_validation",
            "restored value rejected by schema",
            {
                "event": "error",
                "component": "python_validation",
                "message": "restored value rejected by schema",
            },
        )
    ],
)
def test_error_writes_recoverable_fault(capsys, component, message, expected):
    error(component, message)

    assert json_lines(capsys.readouterr().out) == [expected]


@pytest.mark.parametrize(
    ("write", "sink_names"),
    [
        pytest.param(partial(emit, {"diag": "matter_ok"}), (), id="no_sink_stdout_only"),
        pytest.param(partial(emit, {"diag": "matter_ok"}), ("dashboard",), id="one_sink"),
        pytest.param(
            partial(emit, {"diag": "matter_ok"}),
            ("first", "second"),
            id="two_sinks_in_registration_order",
        ),
        pytest.param(partial(event, "matter", "ready"), ("dashboard",), id="event_line"),
        pytest.param(
            partial(error, "occupancy", "radar timed out"), ("dashboard",), id="error_line"
        ),
    ],
)
def test_add_sink_receives_each_stdout_line(capsys, write, sink_names):
    delivered = []
    for sink_name in sink_names:
        add_sink(_recording_sink(delivered, sink_name))

    write()

    out = capsys.readouterr().out
    assert len(json_lines(out)) == 1
    assert delivered == [(sink_name, out.removesuffix("\n")) for sink_name in sink_names]


def _recording_sink(delivered: list, sink_name: str) -> Callable[[str], None]:
    """Build a sink that tags each line with its name, so delivery order across sinks shows.

    Args:
        delivered: Shared list collecting ``(sink_name, line)`` from every sink.
        sink_name: Tag identifying this sink in ``delivered``.

    Returns:
        A sink that appends ``(sink_name, line)`` to ``delivered``.
    """
    return lambda line: delivered.append((sink_name, line))
