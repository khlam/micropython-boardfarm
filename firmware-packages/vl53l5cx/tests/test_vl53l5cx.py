"""Tests for the VL53L5CX wrapper API in firmware-packages/vl53l5cx.

Covers the project-facing convenience methods — read(), start(), and
check_data_ready() — without exercising the vendored init/ranging internals
that require real I²C hardware.
"""

import machine
import pytest
from fake_vl53l5cx import make_results

from vl53l5cx import VL53L5CX, DeviceNotFoundError
from vl53l5cx.vl53l5cx import RESOLUTION_8X8


class _FakeVL53L5CX:
    """No-op register responder: present on the bus, returns zeros."""

    def read(self, _reg: int, nbytes: int) -> bytes:
        """Return nbytes of zeros."""
        return bytes(nbytes)

    def write(self, _reg: int, _data: bytes) -> None:
        """Discard the write."""


def _make_tof() -> VL53L5CX:
    """Reset machine, register a fake at 0x29, return a ready VL53L5CX."""
    machine.reset()
    machine.register_device(0x29, _FakeVL53L5CX())
    sensor = VL53L5CX(sda=0, scl=1)
    sensor._data_read_size = 32
    return sensor


def test_missing_device_raises_device_not_found():
    """Nothing registered on the bus → DeviceNotFoundError, not OSError."""
    machine.reset()
    with pytest.raises(DeviceNotFoundError):
        VL53L5CX(sda=0, scl=1)


def test_read_returns_64_values(monkeypatch):
    tof = _make_tof()
    results = make_results([100] * 64, [5] * 64)
    monkeypatch.setattr(tof, "get_ranging_data", lambda: results)
    assert len(tof.read()) == 64


def test_read_valid_status_5_gives_int(monkeypatch):
    tof = _make_tof()
    results = make_results([500] * 64, [5] * 64)
    monkeypatch.setattr(tof, "get_ranging_data", lambda: results)
    grid = tof.read()
    assert all(v == 500 for v in grid)


def test_read_valid_status_9_gives_int(monkeypatch):
    tof = _make_tof()
    results = make_results([300] * 64, [9] * 64)
    monkeypatch.setattr(tof, "get_ranging_data", lambda: results)
    grid = tof.read()
    assert all(v == 300 for v in grid)


def test_read_invalid_status_gives_none(monkeypatch):
    tof = _make_tof()
    statuses = [0, 1, 2, 3, 4, 6, 7, 8, 10, 11, 12, 13, 255]
    for bad_status in statuses:
        results = make_results([999] * 64, [bad_status] * 64)
        monkeypatch.setattr(tof, "get_ranging_data", lambda r=results: r)
        grid = tof.read()
        assert all(v is None for v in grid), f"status {bad_status} should produce None"


def test_read_mixed_status_maps_individually(monkeypatch):
    tof = _make_tof()
    distances = list(range(64))
    statuses = [5 if i % 2 == 0 else 0 for i in range(64)]
    results = make_results(distances, statuses)
    monkeypatch.setattr(tof, "get_ranging_data", lambda: results)
    grid = tof.read()
    for i, v in enumerate(grid):
        if i % 2 == 0:
            assert v == i
        else:
            assert v is None


def test_check_data_ready_true_on_new_streamcount():
    tof = _make_tof()
    tof._streamcount = 5
    buf = bytes([6, 0x5, 0x5, 0x10])
    tof.i2c.readfrom_mem = lambda _addr, _reg, _size, **_kwargs: buf
    assert tof.check_data_ready() is True
    assert tof._streamcount == 6


def test_check_data_ready_false_same_streamcount():
    tof = _make_tof()
    tof._streamcount = 6
    buf = bytes([6, 0x5, 0x5, 0x10])
    tof.i2c.readfrom_mem = lambda _addr, _reg, _size, **_kwargs: buf
    assert tof.check_data_ready() is False


def test_check_data_ready_false_count_255():
    tof = _make_tof()
    tof._streamcount = 5
    buf = bytes([255, 0x5, 0x5, 0x10])
    tof.i2c.readfrom_mem = lambda _addr, _reg, _size, **_kwargs: buf
    assert tof.check_data_ready() is False


def test_start_sets_8x8_resolution(monkeypatch):
    tof = _make_tof()
    resolutions_set = []
    start_ranging_calls = []

    monkeypatch.setattr(
        type(tof),
        "resolution",
        property(
            fget=lambda _self: RESOLUTION_8X8,
            fset=lambda _self, v: resolutions_set.append(v),
        ),
    )
    monkeypatch.setattr(
        type(tof),
        "ranging_freq",
        property(
            fget=lambda _self: 10,
            fset=lambda _self, _v: None,
        ),
    )
    monkeypatch.setattr(tof, "start_ranging", start_ranging_calls.append)

    tof.start(freq=10)

    assert RESOLUTION_8X8 in resolutions_set
    assert len(start_ranging_calls) == 1


def test_stop_calls_stop_ranging(monkeypatch):
    tof = _make_tof()
    called = []
    monkeypatch.setattr(tof, "stop_ranging", lambda: called.append(True))
    tof.stop()
    assert called == [True]
