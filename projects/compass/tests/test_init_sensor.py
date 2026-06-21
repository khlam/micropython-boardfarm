"""Host CPython pytest tests for init_sensor in compass firmware.

The driver opens its own bus and scans, so init_sensor() takes no arguments and
constructs QMC5883P(bus_id=, sda=, scl=) from BOARD. A fake driver class drives the
happy path, the no_device retry (DeviceNotFoundError), and the init_err (OSError,
e.g. a chip-ID mismatch) retry.
"""

from typing import ClassVar

import pytest

from qmc5883p import DeviceNotFoundError

ADDR = 0x2C


def test_init_sensor_happy_path(init_ns):
    mag = init_ns.ns["init_sensor"]()
    assert mag.address == ADDR
    assert init_ns.status.calls == ["i2c_init"]


def test_init_sensor_retries_when_device_missing(init_ns):
    _FakeMag.script = [DeviceNotFoundError("no device"), None]
    init_ns.ns["init_sensor"]()
    assert init_ns.status.calls == ["i2c_init", "no_device"]


def test_init_sensor_handles_init_err(init_ns):
    # First construction raises (e.g. chip-ID mismatch); second succeeds.
    _FakeMag.script = [OSError("scripted chip-ID fail"), None]
    init_ns.ns["init_sensor"]()
    assert "init_err" in init_ns.status.calls


@pytest.fixture(autouse=True)
def _reset_mag():
    _FakeMag.script = []
    yield


@pytest.fixture
def init_ns(main_ns):
    main_ns.ns["QMC5883P"] = _FakeMag
    return main_ns


class _FakeMag:
    """QMC5883P stand-in: pops `script` per construction to raise or succeed."""

    script: ClassVar[list] = []

    def __init__(self, *, sda, scl, bus_id=0, address=ADDR) -> None:
        if type(self).script:
            outcome = type(self).script.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
        self.address = address
        self.last_status = 0
