"""Tests for the Matter facade's single JSON stdout boundary."""

from collections import namedtuple

import pytest

from matter import DeviceState, FabricState, NetworkState, StateEvent
from matter.emit import emit, emit_state, error
from micropython_stubs.testing import json_lines

# Device states, named fabric-network-window.
_UNCOMMISSIONED = DeviceState(FabricState.UNCOMMISSIONED, NetworkState.DISCONNECTED, False)
_UNCOMMISSIONED_ONLINE = DeviceState(FabricState.UNCOMMISSIONED, NetworkState.CONNECTED, False)
_UNCOMMISSIONED_PAIRABLE = DeviceState(FabricState.UNCOMMISSIONED, NetworkState.DISCONNECTED, True)
_COMMISSIONING = DeviceState(FabricState.COMMISSIONING, NetworkState.DISCONNECTED, False)
_OPERATIONAL_ONLINE_PAIRABLE = DeviceState(FabricState.OPERATIONAL, NetworkState.CONNECTED, True)

_StateCase = namedtuple("_StateCase", ("id", "event", "lines"))


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
    "case",
    [
        _StateCase(
            id="fabric-changed",
            event=StateEvent(_UNCOMMISSIONED, _COMMISSIONING, False),
            lines=[{"event": "fabric", "state": "commissioning"}],
        ),
        _StateCase(
            id="network-changed",
            event=StateEvent(_UNCOMMISSIONED, _UNCOMMISSIONED_ONLINE, False),
            lines=[{"event": "network", "state": "connected"}],
        ),
        _StateCase(
            id="window-opened",
            event=StateEvent(_UNCOMMISSIONED, _UNCOMMISSIONED_PAIRABLE, False),
            lines=[{"event": "commissioning_window", "state": "opened"}],
        ),
        _StateCase(
            id="window-closed",
            event=StateEvent(_UNCOMMISSIONED_PAIRABLE, _UNCOMMISSIONED, False),
            lines=[{"event": "commissioning_window", "state": "closed"}],
        ),
        _StateCase(
            id="failed-attempt-that-changes-no-field",
            event=StateEvent(_UNCOMMISSIONED, _UNCOMMISSIONED, True),
            lines=[{"event": "commissioning", "state": "failed"}],
        ),
        _StateCase(
            id="failed-attempt-and-every-field-changed-in-that-order",
            event=StateEvent(_COMMISSIONING, _OPERATIONAL_ONLINE_PAIRABLE, True),
            lines=[
                {"event": "commissioning", "state": "failed"},
                {"event": "fabric", "state": "operational"},
                {"event": "network", "state": "connected"},
                {"event": "commissioning_window", "state": "opened"},
            ],
        ),
    ],
    ids=lambda case: case.id,
)
def test_emit_state(capsys: pytest.CaptureFixture[str], case: _StateCase):
    """emit_state() writes the failure, then one line per field the event changed.

    Args:
        capsys: Captures stdout.
        case: The state event and the lines written for it.
    """
    emit_state(case.event)

    assert json_lines(capsys.readouterr().out) == case.lines


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
