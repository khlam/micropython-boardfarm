"""Host CPython pytest tests for init_sensor in gyro-stream firmware.

Drives happy path at 0x68, AD0-high fallback to 0x69, the no_device
retry, and the init_err (OSError) retry.
"""

import pytest

PRIMARY = 0x68
SECONDARY = 0x69


def test_init_sensor_primary_address(init_ns):
    init_ns.ns["i2c"] = _FakeBus(scans=[[PRIMARY]])
    imu = init_ns.ns["init_sensor"]()
    assert imu.addr == PRIMARY
    assert init_ns.status.calls == ["i2c_init"]


def test_init_sensor_falls_back_to_secondary(init_ns):
    # AD0 tied high → only 0x69 responds; init_sensor must use it.
    init_ns.ns["i2c"] = _FakeBus(scans=[[SECONDARY]])
    imu = init_ns.ns["init_sensor"]()
    assert imu.addr == SECONDARY


def test_init_sensor_retries_when_device_missing(init_ns):
    init_ns.ns["i2c"] = _FakeBus(scans=[[], [PRIMARY]])
    init_ns.ns["init_sensor"]()
    assert init_ns.status.calls == ["i2c_init", "no_device"]


def test_init_sensor_handles_init_err(init_ns):
    _FakeIMU.raise_oserror_once = True
    init_ns.ns["i2c"] = _FakeBus(scans=[[PRIMARY], [PRIMARY]])
    init_ns.ns["init_sensor"]()
    assert "init_err" in init_ns.status.calls


@pytest.fixture(autouse=True)
def _reset_imu():
    _FakeIMU.raise_oserror_once = False
    _FakeIMU._calls = 0


@pytest.fixture
def init_ns(main_ns):
    main_ns.ns["MPU6050"] = _FakeIMU
    return main_ns


class _FakeBus:
    def __init__(self, *, scans) -> None:
        self._scans = list(scans)

    def scan(self):
        if len(self._scans) == 1:
            return self._scans[0]
        return self._scans.pop(0)


class _FakeIMU:
    """MPU6050 stand-in: records addr + kind, optionally raises on first init."""

    raise_oserror_once = False
    _calls = 0

    def __init__(self, bus, *, addr) -> None:
        type(self)._calls += 1
        if type(self).raise_oserror_once and type(self)._calls == 1:
            raise OSError("scripted WHO_AM_I fail")
        self.bus = bus
        self.addr = addr
        self.kind = "MPU6050"
        self.last_saturated = False
