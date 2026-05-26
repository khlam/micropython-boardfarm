"""Host CPython pytest tests covering i2c_bus dispatch and per-chip backends.

Asserts each chip backend exposes soft_i2c/hard_i2c on the correct pins
at the correct frequencies, the package dispatcher selects the right
backend per os.uname().machine, and the lazy __getattr__ caches so the
unused bus is never instantiated — the load-bearing invariant that lets
the two buses share physical pins without conflict.
"""

import importlib

import pytest

# (machine string, expected backend module, sda pin, scl pin)
_CHIPS = [
    ("RP2040 with RP2040", "i2c_bus.rp2040", 0, 1),
    ("RP2350 with RP2350", "i2c_bus.rp2350", 0, 1),
    ("Generic ESP32S3 module with ESP32S3", "i2c_bus.esp32s3", 1, 2),
]


@pytest.mark.parametrize(
    "chip,backend_mod,_sda,_scl",
    _CHIPS,
    indirect=["chip"],
)
def test_dispatch_picks_correct_backend(chip, backend_mod, _sda, _scl, i2c_bus_module):
    assert i2c_bus_module._backend is importlib.import_module(backend_mod)


@pytest.mark.parametrize(
    "chip,_backend_mod,sda,scl",
    _CHIPS,
    indirect=["chip"],
)
def test_soft_i2c_uses_100khz_on_chip_pins(chip, _backend_mod, sda, scl, i2c_bus_module):
    bus = i2c_bus_module.soft_i2c
    # type(bus).__name__ instead of isinstance: see conftest re: machine-stub seeding.
    assert type(bus).__name__ == "SoftI2C"
    assert bus.sda.id == sda
    assert bus.scl.id == scl
    assert bus.freq == 100_000


@pytest.mark.parametrize(
    "chip,_backend_mod,sda,scl",
    _CHIPS,
    indirect=["chip"],
)
def test_hard_i2c_uses_400khz_on_chip_pins(chip, _backend_mod, sda, scl, i2c_bus_module):
    bus = i2c_bus_module.hard_i2c
    assert type(bus).__name__ == "I2C"
    assert bus.id == 0
    assert bus.sda.id == sda
    assert bus.scl.id == scl
    assert bus.freq == 400_000


@pytest.mark.parametrize("chip", [c[0] for c in _CHIPS], indirect=True)
def test_dispatcher_caches(chip, i2c_bus_module):
    assert i2c_bus_module.soft_i2c is i2c_bus_module.soft_i2c


@pytest.mark.parametrize(
    "chip,backend_mod,_sda,_scl",
    _CHIPS,
    indirect=["chip"],
)
def test_backend_caches(chip, backend_mod, _sda, _scl):
    # Backend's own __getattr__ also caches via globals().
    backend = importlib.import_module(backend_mod)
    assert backend.soft_i2c is backend.soft_i2c
    assert backend.hard_i2c is backend.hard_i2c


@pytest.mark.parametrize("chip", [c[0] for c in _CHIPS], indirect=True)
def test_dispatcher_unknown_attribute_raises(chip, i2c_bus_module):
    with pytest.raises(AttributeError):
        _ = i2c_bus_module.spi_bus


@pytest.mark.parametrize(
    "chip,backend_mod,_sda,_scl",
    _CHIPS,
    indirect=["chip"],
)
def test_backend_unknown_attribute_raises(chip, backend_mod, _sda, _scl):
    backend = importlib.import_module(backend_mod)
    with pytest.raises(AttributeError):
        backend.__getattr__("spi_bus")


@pytest.fixture
def i2c_bus_module(chip):
    """Re-import i2c_bus after `chip` patches os.uname so dispatch re-runs."""
    return importlib.import_module("i2c_bus")
