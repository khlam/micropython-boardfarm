"""Host CPython pytest tests for init_sensor() in multizone-ranging firmware.

The driver opens its own bus and scans, so init_sensor() takes no arguments and
constructs VL53L5CX(sda=, scl=) from BOARD, then calls init()/start(). Covers:
happy path, no_device retry (DeviceNotFoundError from the constructor), init error
retry (OSError from the constructor), and ValueError/RuntimeError from init()
(e.g. a poll timeout during firmware loading).
"""

from typing import ClassVar

import pytest

from vl53l5cx import DeviceNotFoundError


def test_init_sensor_happy_path(init_ns):
    tof = init_ns.ns["init_sensor"]()
    assert isinstance(tof, _FakeVL53L5CX)
    assert tof._inited is True
    assert tof._started is True
    assert init_ns.status.calls == ["i2c_init"]


def test_init_sensor_retries_when_device_missing(init_ns):
    _FakeVL53L5CX.script = [DeviceNotFoundError("no device"), None]
    init_ns.ns["init_sensor"]()
    assert init_ns.status.calls == ["i2c_init", "no_device"]


def test_init_sensor_retries_on_oserror(init_ns):
    _FakeVL53L5CX.script = [OSError("bus fault"), None]
    init_ns.ns["init_sensor"]()
    assert "init_err" in init_ns.status.calls


def test_init_sensor_retries_on_value_error(init_ns):
    call = {"n": 0}

    class _FailOnce(_FakeVL53L5CX):
        def init(self):
            call["n"] += 1
            if call["n"] == 1:
                raise ValueError("poll_for_answer failed")
            super().init()

    init_ns.ns["VL53L5CX"] = _FailOnce
    init_ns.ns["init_sensor"]()
    assert "init_err" in init_ns.status.calls


def test_init_sensor_retries_on_runtime_error(init_ns):
    call = {"n": 0}

    class _RTEOnce(_FakeVL53L5CX):
        def init(self):
            call["n"] += 1
            if call["n"] == 1:
                raise RuntimeError("driver timeout")
            super().init()

    init_ns.ns["VL53L5CX"] = _RTEOnce
    init_ns.ns["init_sensor"]()
    assert "init_err" in init_ns.status.calls


@pytest.fixture(autouse=True)
def _reset_tof():
    _FakeVL53L5CX.script = []
    yield


@pytest.fixture
def init_ns(main_ns):
    """Inject the fake VL53L5CX class into the main.py namespace."""
    main_ns.ns["VL53L5CX"] = _FakeVL53L5CX
    return main_ns


class _FakeVL53L5CX:
    """VL53L5CX stand-in: pops `script` per construction, records init()/start()."""

    script: ClassVar[list] = []

    def __init__(self, *, sda, scl) -> None:
        if type(self).script:
            outcome = type(self).script.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
        self.addr = 0x29
        self._inited = False
        self._started = False
        self._freq = None

    def init(self) -> None:
        self._inited = True

    def start(self, freq=10) -> None:
        self._started = True
        self._freq = freq
