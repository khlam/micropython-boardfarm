"""Tests for the Matter facade's single JSON stdout boundary."""

import json

from matter.emit import emit, error, event


def test_emit_writes_one_json_object(capsys):
    emit({"answer": 42, "ok": True})

    assert _output(capsys) == [{"answer": 42, "ok": True}]


def test_event_writes_named_transition(capsys):
    event("matter", "ready")

    assert _output(capsys) == [{"event": "matter", "state": "ready"}]


def test_error_writes_recoverable_fault(capsys):
    error("python_callback", "callback raised an exception")

    assert _output(capsys) == [
        {
            "event": "error",
            "component": "python_callback",
            "message": "callback raised an exception",
        }
    ]


def _output(capsys):
    """Parse every non-empty stdout line as JSON."""
    return [json.loads(line) for line in capsys.readouterr().out.splitlines() if line]
