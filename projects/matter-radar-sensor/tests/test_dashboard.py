"""On-device dashboard polling, startup, and failure-isolation tests."""

import asyncio

import _matter
import pytest

from micropython_stubs.testing import StopLoopError, json_lines

_FABRIC = (1, 0x1234, 0x5678, 0xFFF1, "controller")


def test_no_network_address_polls_and_clears_failure_period(load_application):
    boot = load_application()

    result = asyncio.run(boot.application._update_dashboard("old-address", failure_reported=True))

    assert result == (None, False, boot.module._ADDRESS_POLL_MS)
    assert boot.server.start_calls == 0


def test_address_lookup_error_is_reported_once_per_failure_period(load_application, capsys):
    boot = load_application()
    capsys.readouterr()
    _matter.fail_next("network_address")

    first = asyncio.run(boot.application._update_dashboard(None, failure_reported=False))
    _matter.fail_next("network_address")
    second = asyncio.run(boot.application._update_dashboard(first[0], failure_reported=first[1]))

    lines = json_lines(capsys.readouterr().out)
    errors = [line for line in lines if line.get("component") == "dashboard"]
    assert len(errors) == 1
    assert "injected network_address failure" in errors[0]["message"]
    assert first == (None, True, boot.module._ADDRESS_POLL_MS)
    assert second == (None, True, boot.module._ADDRESS_POLL_MS)


def test_bind_failure_retries_once_per_period_without_changing_product_state(
    load_application, capsys
):
    boot = load_application(fabrics=(_FABRIC,))
    application = boot.application
    application._set_radar_health(healthy=True)
    _matter.set_network_address("192.0.2.10")
    boot.server.start_errors.extend([OSError("address in use"), OSError("address in use")])
    before = (
        application._occupancy_state,
        application._published_occupancy,
        application._radar_healthy,
    )
    capsys.readouterr()

    first = asyncio.run(application._update_dashboard(None, failure_reported=False))
    second = asyncio.run(application._update_dashboard(first[0], failure_reported=first[1]))

    assert first == (None, True, boot.module._DASHBOARD_RETRY_MS)
    assert second == (None, True, boot.module._DASHBOARD_RETRY_MS)
    assert boot.server.running is False
    assert (
        application._occupancy_state,
        application._published_occupancy,
        application._radar_healthy,
    ) == before
    lines = json_lines(capsys.readouterr().out)
    assert len([line for line in lines if line.get("component") == "dashboard"]) == 1


def test_successful_start_reports_url_and_returns_to_polling(load_application, capsys):
    boot = load_application()
    _matter.set_network_address("192.0.2.20")
    capsys.readouterr()

    result = asyncio.run(boot.application._update_dashboard(None, failure_reported=True))

    assert result == ("192.0.2.20", False, boot.module._ADDRESS_POLL_MS)
    assert boot.server.running is True
    assert boot.server.start_calls == 1
    assert json_lines(capsys.readouterr().out) == [
        {
            "event": "dashboard",
            "state": "ready",
            "url": "http://192.0.2.20/",
        }
    ]


def test_running_server_reports_only_address_changes(load_application, capsys):
    boot = load_application()
    boot.server.running = True
    _matter.set_network_address("192.0.2.30")
    capsys.readouterr()

    unchanged = asyncio.run(
        boot.application._update_dashboard("192.0.2.30", failure_reported=False)
    )
    _matter.set_network_address("192.0.2.31")
    changed = asyncio.run(boot.application._update_dashboard(unchanged[0], failure_reported=False))

    assert unchanged == ("192.0.2.30", False, boot.module._ADDRESS_POLL_MS)
    assert changed == ("192.0.2.31", False, boot.module._ADDRESS_POLL_MS)
    assert json_lines(capsys.readouterr().out) == [
        {
            "event": "dashboard",
            "state": "ready",
            "url": "http://192.0.2.31/",
        }
    ]


def test_dashboard_supervisor_observes_boot_and_poll_delays(load_application, monkeypatch):
    boot = load_application()
    sleeps = []
    updates = []

    async def update(address, *, failure_reported):
        updates.append((address, failure_reported))
        return "192.0.2.40", False, 1234

    async def sleep_ms(delay_ms):
        sleeps.append(delay_ms)
        if len(sleeps) == 2:
            raise StopLoopError

    monkeypatch.setattr(boot.application, "_update_dashboard", update)
    monkeypatch.setattr(asyncio, "sleep_ms", sleep_ms)

    with pytest.raises(StopLoopError):
        asyncio.run(boot.application._run_dashboard())

    assert sleeps == [boot.module._DASHBOARD_BOOT_DELAY_MS, 1234]
    assert updates == [(None, False)]
