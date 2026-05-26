"""Host CPython pytest tests for init_sensor and soft_reset_sensor in distance-stream firmware.

Drives both helpers with a scriptable fake I²C bus and a fake VL53L0X.
Covers happy path, no_device retry, init_err retry, and the three
soft_reset outcomes (booted, poll-timeout, mid-write OSError).
"""

import pytest

TOF_ADDRESS = 0x29
_REG_MODEL_ID = 0xC0
_MODEL_ID_BOOTED = 0xEE


def test_init_sensor_happy_path(init_ns):
    bus = _FakeBus(
        scans=[[TOF_ADDRESS]],
        mem_reads={_REG_MODEL_ID: bytes([_MODEL_ID_BOOTED])},
    )
    init_ns.ns["i2c"] = bus
    tof = init_ns.ns["init_sensor"]()
    assert isinstance(tof, _FakeVL53L0X)
    assert tof._budget == 20_000  # TIMING_BUDGET_US
    assert tof._started is True
    assert init_ns.status.calls == ["i2c_init"]


def test_init_sensor_retries_when_device_missing(init_ns):
    bus = _FakeBus(
        scans=[[], [TOF_ADDRESS]],
        mem_reads={_REG_MODEL_ID: bytes([_MODEL_ID_BOOTED])},
    )
    init_ns.ns["i2c"] = bus
    init_ns.ns["init_sensor"]()
    assert init_ns.status.calls == ["i2c_init", "no_device"]


def test_init_sensor_handles_init_err(init_ns, monkeypatch):
    bus = _FakeBus(
        scans=[[TOF_ADDRESS]],
        mem_reads={_REG_MODEL_ID: bytes([_MODEL_ID_BOOTED])},
    )
    init_ns.ns["i2c"] = bus

    call = {"n": 0}
    real_init = _FakeVL53L0X.__init__

    def maybe_raise(self, *a, **kw):
        call["n"] += 1
        if call["n"] == 1:
            raise OSError("first attempt fails")
        real_init(self, *a, **kw)

    monkeypatch.setattr(_FakeVL53L0X, "__init__", maybe_raise)
    init_ns.ns["init_sensor"]()
    assert "init_err" in init_ns.status.calls


def test_init_sensor_handles_runtime_error_during_init(init_ns):
    # RuntimeError (driver poll timeout) is also caught and routed to init_err.
    bus = _FakeBus(
        scans=[[TOF_ADDRESS], [TOF_ADDRESS]],
        mem_reads={_REG_MODEL_ID: bytes([_MODEL_ID_BOOTED])},
    )
    init_ns.ns["i2c"] = bus

    call = {"n": 0}

    class _RTLOnce(_FakeVL53L0X):
        def __init__(self, *a, **kw) -> None:
            call["n"] += 1
            if call["n"] == 1:
                raise RuntimeError("driver poll timeout")
            super().__init__(*a, **kw)

    init_ns.ns["VL53L0X"] = _RTLOnce
    init_ns.ns["init_sensor"]()
    assert "init_err" in init_ns.status.calls


def test_soft_reset_sensor_success(main_ns):
    bus = _FakeBus(
        scans=[[TOF_ADDRESS]],
        mem_reads={_REG_MODEL_ID: bytes([_MODEL_ID_BOOTED])},
    )
    assert main_ns.ns["soft_reset_sensor"](bus) is True
    # writes: (addr, 0xBF, b"\x00") then (addr, 0xBF, b"\x01")
    regs = [w[1] for w in bus.writes]
    assert regs == [0xBF, 0xBF]


def test_soft_reset_sensor_times_out(main_ns):
    bus = _FakeBus(
        scans=[[TOF_ADDRESS]],
        mem_reads={_REG_MODEL_ID: b"\x00"},  # never reads booted
    )
    assert main_ns.ns["soft_reset_sensor"](bus) is False


def test_soft_reset_sensor_oserror_returns_false(main_ns):
    bus = _FakeBus(scans=[[TOF_ADDRESS]], write_raises_on={0xBF})
    assert main_ns.ns["soft_reset_sensor"](bus) is False


@pytest.fixture
def init_ns(main_ns):
    """Inject the fake VL53L0X class into the main.py namespace."""
    main_ns.ns["VL53L0X"] = _FakeVL53L0X
    return main_ns


class _FakeBus:
    """Bus stub: scriptable `scan()` plus per-register `readfrom_mem` answers."""

    def __init__(self, *, scans, mem_reads=None, write_raises_on=None) -> None:
        self._scans = list(scans)
        self._mem_reads = mem_reads or {}
        self._write_raises_on = write_raises_on or set()
        self.writes: list[tuple[int, int, bytes]] = []

    def scan(self):
        if len(self._scans) == 1:
            return self._scans[0]
        return self._scans.pop(0)

    def readfrom_mem(self, _addr, reg, _n):
        return self._mem_reads.get(reg, b"\x00")

    def writeto_mem(self, _addr, reg, buf):
        if reg in self._write_raises_on:
            raise OSError("scripted write fail")
        self.writes.append((_addr, reg, bytes(buf)))


class _FakeVL53L0X:
    """VL53L0X stand-in: records timing-budget and start calls."""

    def __init__(self, bus, *, skip_spad_info=False, interrupt_status_mask=0) -> None:
        self.bus = bus
        self.skip_spad_info = skip_spad_info
        self.interrupt_status_mask = interrupt_status_mask
        self.address = TOF_ADDRESS
        self._budget = None
        self._started = False

    def set_measurement_timing_budget(self, budget):
        self._budget = budget

    def start(self):
        self._started = True
