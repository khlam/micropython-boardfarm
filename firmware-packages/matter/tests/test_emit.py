"""Tests for the Matter facade's single JSON stdout boundary."""

import pytest

from matter.emit import emit, error, event
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
def test_emit_writes_one_json_line(capsys: pytest.CaptureFixture[str], obj: dict[str, object]):
    """emit() writes the object as exactly one JSON line, even with newlines inside strings.

    Args:
        capsys: Captures stdout.
        obj: The object to emit.
    """
    emit(obj)

    out = capsys.readouterr().out
    assert out.count("\n") == 1
    assert out.endswith("\n")
    assert json_lines(out) == [obj]


@pytest.mark.parametrize(
    ("name", "state", "expected"),
    [("matter", "ready", {"event": "matter", "state": "ready"})],
)
def test_event_writes_named_transition(
    capsys: pytest.CaptureFixture[str], name: str, state: str, expected: dict[str, str]
):
    """event() writes one line naming the component and its new state.

    Args:
        capsys: Captures stdout.
        name: The component whose state changed.
        state: Its new state.
        expected: The line written.
    """
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
def test_error_writes_recoverable_fault(
    capsys: pytest.CaptureFixture[str], component: str, message: str, expected: dict[str, str]
):
    """error() writes one error line naming the component and the fault.

    Args:
        capsys: Captures stdout.
        component: The component that failed.
        message: What went wrong.
        expected: The line written.
    """
    error(component, message)

    assert json_lines(capsys.readouterr().out) == [expected]
