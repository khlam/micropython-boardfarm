"""Tests for the Matter facade's single JSON stdout boundary."""

from matter.emit import emit, error, event
from micropython_stubs.testing import json_lines


def test_emit_writes_one_json_object(capsys):
    emit({"answer": 42, "ok": True})

    assert json_lines(capsys.readouterr().out) == [{"answer": 42, "ok": True}]


def test_event_writes_named_transition(capsys):
    event("matter", "ready")

    assert json_lines(capsys.readouterr().out) == [{"event": "matter", "state": "ready"}]


def test_error_writes_recoverable_fault(capsys):
    error("python_validation", "restored value rejected by schema")

    assert json_lines(capsys.readouterr().out) == [
        {
            "event": "error",
            "component": "python_validation",
            "message": "restored value rejected by schema",
        }
    ]
