"""Host CPython pytest tests for init_sensor() in multizone-ranging firmware.

Covers: happy path, no_device retry, init error retry, and ValueError from
the driver (e.g. a poll timeout during firmware loading).
"""

import pytest

_TOF_ADDRESS = 0x29


def test_init_sensor_happy_path(init_ns):
    bus = _FakeBus(scans=[[_TOF_ADDRESS]])
    init_ns.ns["i2c"] = bus
    tof = init_ns.ns["init_sensor"]()
    assert isinstance(tof, _FakeVL53L5CX)
    assert tof._inited is True
    assert tof._started is True
    assert init_ns.status.calls == ["i2c_init"]


def test_init_sensor_retries_when_device_missing(init_ns):
    bus = _FakeBus(scans=[[], [_TOF_ADDRESS]])
    init_ns.ns["i2c"] = bus
    init_ns.ns["init_sensor"]()
    assert init_ns.status.calls == ["i2c_init", "no_device"]


def test_init_sensor_retries_on_oserror(init_ns, monkeypatch):
    bus = _FakeBus(scans=[[_TOF_ADDRESS], [_TOF_ADDRESS]])
    init_ns.ns["i2c"] = bus

    call = {"n": 0}
    real_init = _FakeVL53L5CX.__init__

    def maybe_raise(self, *a, **kw):
        call["n"] += 1
        if call["n"] == 1:
            raise OSError("bus fault")
        real_init(self, *a, **kw)

    monkeypatch.setattr(_FakeVL53L5CX, "__init__", maybe_raise)
    init_ns.ns["init_sensor"]()
    assert "init_err" in init_ns.status.calls


def test_init_sensor_retries_on_value_error(init_ns, monkeypatch):
    bus = _FakeBus(scans=[[_TOF_ADDRESS], [_TOF_ADDRESS]])
    init_ns.ns["i2c"] = bus

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


def test_init_sensor_retries_on_runtime_error(init_ns, monkeypatch):
    bus = _FakeBus(scans=[[_TOF_ADDRESS], [_TOF_ADDRESS]])
    init_ns.ns["i2c"] = bus

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


@pytest.fixture
def init_ns(main_ns):
    """Inject the fake VL53L5CX class into the main.py namespace."""
    main_ns.ns["VL53L5CX"] = _FakeVL53L5CX
    return main_ns


class _FakeBus:
    """Bus stub with a scriptable scan() list."""

    def __init__(self, *, scans) -> None:
        self._scans = list(scans)

    def scan(self):
        if len(self._scans) == 1:
            return self._scans[0]
        return self._scans.pop(0)


class _FakeVL53L5CX:
    """VL53L5CX stand-in: records init() and start() calls."""

    def __init__(self, bus) -> None:
        self.bus = bus
        self._inited = False
        self._started = False
        self._freq = None

    def init(self) -> None:
        self._inited = True

    def start(self, freq=10) -> None:
        self._started = True
        self._freq = freq
