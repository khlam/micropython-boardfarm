"""Host CPython pytest tests for init_sensor in compass firmware.

Drives the happy path at the fixed 0x2C address, the no_device retry, and the
init_err (OSError, including a chip-ID mismatch) retry.
"""

import pytest

ADDR = 0x2C


def test_init_sensor_happy_path(init_ns):
    mag = init_ns.ns["init_sensor"](_FakeBus(scans=[[ADDR]]))
    assert mag.address == ADDR
    assert init_ns.status.calls == ["i2c_init"]


def test_init_sensor_retries_when_device_missing(init_ns):
    init_ns.ns["init_sensor"](_FakeBus(scans=[[], [ADDR]]))
    assert init_ns.status.calls == ["i2c_init", "no_device"]


def test_init_sensor_handles_init_err(init_ns):
    # First construction raises (e.g. chip-ID mismatch); second succeeds.
    _FakeMag.raise_oserror_once = True
    init_ns.ns["init_sensor"](_FakeBus(scans=[[ADDR], [ADDR]]))
    assert "init_err" in init_ns.status.calls


@pytest.fixture(autouse=True)
def _reset_mag():
    _FakeMag.raise_oserror_once = False
    _FakeMag._calls = 0
    yield


@pytest.fixture
def init_ns(main_ns):
    main_ns.ns["QMC5883P"] = _FakeMag
    return main_ns


class _FakeBus:
    def __init__(self, *, scans) -> None:
        self._scans = list(scans)

    def scan(self):
        if len(self._scans) == 1:
            return self._scans[0]
        return self._scans.pop(0)


class _FakeMag:
    """QMC5883P stand-in: records address, optionally raises on first init."""

    raise_oserror_once = False
    _calls = 0

    def __init__(self, bus, address=ADDR) -> None:
        type(self)._calls += 1
        if type(self).raise_oserror_once and type(self)._calls == 1:
            raise OSError("scripted chip-ID fail")
        self.bus = bus
        self.address = address
        self.last_status = 0
