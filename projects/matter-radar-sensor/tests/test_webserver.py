"""On-device dashboard polling, startup, and failure-isolation tests."""

import asyncio
from unittest.mock import AsyncMock, Mock

import _matter
import pytest

from micropython_stubs.testing import StopLoopError, json_lines


def test_no_network_address_polls_and_clears_failure_period(load_application):
    boot = load_application()
    web = boot.application._webserver
    web._address = "old-address"
    web._failed = True

    delay = web._update_address(boot.application._node.network_address)

    assert delay == boot.webserver_module._ADDRESS_POLL_MS
    assert web._address is None
    assert web._failed is False
    assert web._task is None


def test_address_lookup_error_is_reported_once_per_failure_period(load_application, capsys):
    boot = load_application()
    web = boot.application._webserver
    capsys.readouterr()

    delays = []
    for _ in range(2):
        _matter.fail_next("network_address")
        delays.append(web._update_address(boot.application._node.network_address))

    errors = [
        line for line in json_lines(capsys.readouterr().out) if line.get("component") == "dashboard"
    ]
    assert delays == [boot.webserver_module._DASHBOARD_RETRY_MS] * 2
    assert len(errors) == 1
    assert "injected network_address failure" in errors[0]["message"]


def test_guard_suspension_is_reported_once_and_leaves_the_product_state_alone(
    load_application, capsys
):
    boot = load_application(commissioned=True)
    application = boot.application
    web = application._webserver
    _matter.set_network_address("192.0.2.10")
    web._task = object()
    web._server.state = "cooldown"
    web._server.reason = "heap"
    before = (
        application._occupancy_policy.occupied,
        application._published_occupancy,
        application._radar_healthy,
    )
    capsys.readouterr()

    web._update_address(application._node.network_address)
    web._update_address(application._node.network_address)
    assert (
        application._occupancy_policy.occupied,
        application._published_occupancy,
        application._radar_healthy,
    ) == before
    lines = json_lines(capsys.readouterr().out)
    assert lines == [{"diag": "web", "state": "cooldown", "reason": "heap"}]
    assert web._address is None


def test_successful_start_reports_url_and_returns_to_polling(load_application, capsys):
    boot = load_application()
    web = boot.application._webserver
    web._failed = True
    web._task = object()
    web._server.state = "running"
    _matter.set_network_address("192.0.2.20")
    capsys.readouterr()

    delay = web._update_address(boot.application._node.network_address)

    assert delay == boot.webserver_module._ADDRESS_POLL_MS
    assert web._address == "192.0.2.20"
    assert web._failed is False
    assert json_lines(capsys.readouterr().out) == [
        {"diag": "web", "state": "running"},
        {
            "event": "dashboard",
            "state": "ready",
            "url": "http://192.0.2.20/",
        },
    ]


def test_running_server_reports_only_address_changes(load_application, capsys):
    boot = load_application()
    web = boot.application._webserver
    web._server.state = "running"
    web._reported_state = ("running", None)
    web._task = object()
    web._address = "192.0.2.30"
    _matter.set_network_address("192.0.2.30")
    capsys.readouterr()

    web._update_address(boot.application._node.network_address)
    _matter.set_network_address("192.0.2.31")
    web._update_address(boot.application._node.network_address)

    assert web._address == "192.0.2.31"
    assert json_lines(capsys.readouterr().out) == [
        {
            "event": "dashboard",
            "state": "ready",
            "url": "http://192.0.2.31/",
        }
    ]


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


def test_recovered_listener_announces_same_address_again(load_application, capsys):
    boot = load_application()
    web = boot.application._webserver
    network_address = boot.application._node.network_address
    web._task = object()
    web._server.state = "running"
    _matter.set_network_address("192.0.2.20")
    web._update_address(network_address)
    capsys.readouterr()
    web._server.state = "cooldown"
    web._server.reason = "heap"
    web._update_address(network_address)
    web._server.state = "running"
    web._server.reason = None
    web._update_address(network_address)
    lines = json_lines(capsys.readouterr().out)
    assert lines == [
        {"diag": "web", "state": "cooldown", "reason": "heap"},
        {"diag": "web", "state": "running"},
        {"event": "dashboard", "state": "ready", "url": "http://192.0.2.20/"},
    ]
