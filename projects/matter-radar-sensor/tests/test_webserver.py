"""On-device dashboard polling, startup, and failure-isolation tests."""

import asyncio
from unittest.mock import AsyncMock, Mock

import matter_native
import pytest

from micropython_stubs.testing import StopLoopError, json_lines

# An address step whose lookup raises instead of returning an address.
_LOOKUP_FAILS = object()
_POLL = "_ADDRESS_POLL_MS"
_RETRY = "_DASHBOARD_RETRY_MS"

_STOPPED = {"diag": "web", "state": "stopped"}
_RUNNING = {"diag": "web", "state": "running"}
_HEAP_COOLDOWN = {"diag": "web", "state": "cooldown", "reason": "heap"}
_LOOKUP_ERROR = {
    "event": "error",
    "component": "dashboard",
    "message": "[Errno 5] injected network_address failure",
}


def _ready(address):
    """Return the announcement of a dashboard listening at ``address``."""
    return {"event": "dashboard", "state": "ready", "url": f"http://{address}/"}


@pytest.mark.parametrize(
    ("steps", "lines", "serving"),
    [
        pytest.param(
            [("stopped", None, None, _POLL)],
            [_STOPPED],
            False,
            id="no-address-starts-no-server",
        ),
        pytest.param(
            [("stopped", None, "192.0.2.20", _POLL)],
            [_STOPPED],
            True,
            id="address-starts-the-server-but-waits-for-it-to-listen",
        ),
        pytest.param(
            [("running", None, "192.0.2.20", _POLL)],
            [_RUNNING, _ready("192.0.2.20")],
            True,
            id="listening-server-announces-its-address",
        ),
        pytest.param(
            [
                ("running", None, "192.0.2.30", _POLL),
                ("running", None, "192.0.2.30", _POLL),
                ("running", None, "192.0.2.31", _POLL),
            ],
            [_RUNNING, _ready("192.0.2.30"), _ready("192.0.2.31")],
            True,
            id="only-address-changes-are-announced",
        ),
        pytest.param(
            [("running", None, _LOOKUP_FAILS, _RETRY), ("running", None, _LOOKUP_FAILS, _RETRY)],
            [_RUNNING, _LOOKUP_ERROR],
            False,
            id="lookup-error-reported-once-per-failure-period",
        ),
        pytest.param(
            [
                ("running", None, _LOOKUP_FAILS, _RETRY),
                ("running", None, None, _POLL),
                ("running", None, _LOOKUP_FAILS, _RETRY),
            ],
            [_RUNNING, _LOOKUP_ERROR, _LOOKUP_ERROR],
            False,
            id="successful-lookup-ends-the-failure-period",
        ),
        pytest.param(
            [
                ("running", None, "192.0.2.20", _POLL),
                ("running", None, _LOOKUP_FAILS, _RETRY),
                ("running", None, "192.0.2.20", _POLL),
            ],
            [_RUNNING, _ready("192.0.2.20"), _LOOKUP_ERROR],
            True,
            id="lookup-error-keeps-the-announced-address",
        ),
        pytest.param(
            [("cooldown", "heap", "192.0.2.10", _POLL), ("cooldown", "heap", "192.0.2.10", _POLL)],
            [_HEAP_COOLDOWN],
            True,
            id="suspension-reported-once-and-address-withheld",
        ),
        pytest.param(
            [
                ("running", None, "192.0.2.20", _POLL),
                ("cooldown", "heap", "192.0.2.20", _POLL),
                ("running", None, "192.0.2.20", _POLL),
            ],
            [_RUNNING, _ready("192.0.2.20"), _HEAP_COOLDOWN, _RUNNING, _ready("192.0.2.20")],
            True,
            id="recovered-listener-announces-the-same-address-again",
        ),
    ],
)
def test_address_check(load_application, capsys, steps, lines, serving):
    """Each address check reports the server and address once per change.

    A step sets the server's lifecycle state and reason and the address Matter
    returns, then expects the delay before the next check. ``serving`` is
    whether the checks started the server's background task. No step touches
    occupancy or the status pixel.
    """
    boot = load_application(commissioned=True)
    application = boot.application
    web = application._webserver
    product = (application._occupancy.occupancy, list(application._status._pixel.writes))
    capsys.readouterr()

    async def run():
        delays = []
        for state, reason, address, _delay in steps:
            web._server.state, web._server.reason = state, reason
            if address is _LOOKUP_FAILS:
                matter_native.fail_next("network_address")
            else:
                matter_native.set_network_address(address)
            delays.append(web._update_address(application._node.network_address))
        return delays, bool(asyncio.all_tasks() - {asyncio.current_task()})

    assert asyncio.run(run()) == (
        [getattr(boot.webserver_module, step[-1]) for step in steps],
        serving,
    )
    assert json_lines(capsys.readouterr().out) == lines
    assert (application._occupancy.occupancy, application._status._pixel.writes) == product


def test_dashboard_supervisor_sheds_work_when_reporting_runs_out_of_memory(
    load_application, monkeypatch
):
    boot = load_application()
    web = boot.application._webserver
    update = Mock(side_effect=[MemoryError(), StopLoopError()])
    sleep = AsyncMock()
    monkeypatch.setattr(web, "_update_address", update)
    monkeypatch.setattr(asyncio, "sleep_ms", sleep)
    with pytest.raises(StopLoopError):
        asyncio.run(web.run(boot.application._node.network_address))
    assert web._server.state == "cooldown"
    assert web._server.reason == "memory"
    assert [call.args[0] for call in sleep.await_args_list] == [
        boot.webserver_module._DASHBOARD_BOOT_DELAY_MS,
        boot.webserver_module._DASHBOARD_RETRY_MS,
    ]
