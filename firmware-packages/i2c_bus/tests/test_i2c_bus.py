"""Host CPython tests for the i2c_bus factories.

Each factory takes flat pin numbers and returns a bus on those pins at the
right default frequency. There is no chip dispatch here — the driver passes the
pins from the project's BOARD table, so these tests just assert they wire through.
"""

from i2c_bus import DeviceNotFoundError, hard_i2c, soft_i2c


def test_hard_i2c_builds_on_wired_pins():
    bus = hard_i2c(bus_id=0, sda=4, scl=5)
    # type name instead of isinstance: the machine stub is a separate import path.
    assert type(bus).__name__ == "I2C"
    assert bus.id == 0
    assert bus.sda.id == 4
    assert bus.scl.id == 5
    assert bus.freq == 400_000


def test_soft_i2c_builds_on_wired_pins():
    bus = soft_i2c(sda=4, scl=5)
    assert type(bus).__name__ == "SoftI2C"
    assert bus.sda.id == 4
    assert bus.scl.id == 5
    assert bus.freq == 100_000


def test_hard_i2c_selects_peripheral_id():
    assert hard_i2c(bus_id=1, sda=6, scl=7).id == 1


def test_freq_override():
    assert soft_i2c(sda=0, scl=1, freq=50_000).freq == 50_000
    assert hard_i2c(bus_id=0, sda=0, scl=1, freq=1_000_000).freq == 1_000_000


def test_device_not_found_is_an_exception():
    assert issubclass(DeviceNotFoundError, Exception)
