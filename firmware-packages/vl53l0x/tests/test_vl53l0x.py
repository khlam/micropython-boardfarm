"""Host CPython pytest tests for the VL53L0X driver against the register simulator.

The simulator is faithful enough to let the driver scan, soft-reset, complete
init, start continuous ranging, and return a configured distance. The driver
opens its own bus from flat pins, so the fake is registered in the machine
stub's device registry and the driver's internal scan() finds it. It does *not*
exercise NACK retries, clock-stretch timeouts, or the ESP32-S3 bit-6 quirk —
those need hardware.
"""

import machine
import pytest
from fake_vl53l0x import FakeVL53L0X

from vl53l0x import VL53L0X, DeviceNotFoundError


def _register_fake(**kwargs):
    """Reset machine state and register a FakeVL53L0X at 0x29."""
    machine.reset()
    dev = FakeVL53L0X(**kwargs)
    machine.register_device(0x29, dev)
    return dev


def test_driver_inits_with_skip_spad_info():
    _register_fake()
    tof = VL53L0X(sda=0, scl=1, skip_spad_info=True, interrupt_status_mask=0x07)

    assert tof.address == 0x29
    assert tof.skip_spad_info is True


def test_missing_device_raises_device_not_found():
    """Nothing registered on the bus → DeviceNotFoundError, not OSError."""
    machine.reset()
    with pytest.raises(DeviceNotFoundError):
        VL53L0X(sda=0, scl=1)


def test_read_returns_simulated_distance():
    fake_tof = _register_fake()
    tof = VL53L0X(sda=0, scl=1, skip_spad_info=True, interrupt_status_mask=0x07)
    tof.start()

    fake_tof.set_distance(1234)
    assert tof.read() == 1234

    fake_tof.set_distance(50)
    assert tof.read() == 50


def test_esp32_wider_mask_is_honored():
    """Driver must honor interrupt_status_mask=0xFF (ESP32-S3 path).

    The ESP32-S3 breakout signals "done" via bit 6 of 0x13; bits 0-2 never
    set. If the driver ignored its mask parameter, read() would
    TimeoutError.
    """
    dev = _register_fake(interrupt_status_after_write=0x40)

    tof = VL53L0X(sda=0, scl=1, skip_spad_info=True, interrupt_status_mask=0xFF)
    tof.start()
    dev.set_distance(777)
    assert tof.read() == 777


def test_soft_reset_success():
    """Soft-reset completes when model ID is readable as 0xEE."""
    _register_fake(soft_reset_behavior="normal")

    tof = VL53L0X(sda=0, scl=1, skip_spad_info=True, interrupt_status_mask=0x07)
    assert tof.address == 0x29


def test_soft_reset_timeout_is_swallowed():
    """Soft-reset timeout (model ID never becomes 0xEE) is swallowed.

    Init continues anyway, matching the driver docstring: "A no-show is
    swallowed — init() runs regardless, matching the chip's tolerance
    for a skipped reset."
    """
    _register_fake(soft_reset_behavior="timeout")

    tof = VL53L0X(sda=0, scl=1, skip_spad_info=True, interrupt_status_mask=0x07)
    assert tof.address == 0x29


def test_soft_reset_oserror_is_swallowed():
    """Soft-reset OSError during poll is swallowed.

    If an I²C error occurs while polling the model ID, the error is caught
    and init continues anyway.
    """
    _register_fake(soft_reset_behavior="error")

    tof = VL53L0X(sda=0, scl=1, skip_spad_info=True, interrupt_status_mask=0x07)
    assert tof.address == 0x29


def test_int_pin_wires_input_irq_and_data_ready_flows():
    """int_pin adds an input Pin whose falling-edge IRQ raises data_ready.

    Simulates the GPIO1 falling edge via the machine stub's fire_irq, then
    confirms read() returns the distance and consumes (clears) the flag.
    """
    fake_tof = _register_fake()
    tof = VL53L0X(sda=0, scl=1, skip_spad_info=True, interrupt_status_mask=0x07, int_pin=4)
    tof.start()

    assert (4, machine.Pin.IN) in machine.pin_constructions
    assert tof.data_ready is False

    machine.fire_irq(4)  # the chip signalled a new sample on GPIO1
    assert tof.data_ready is True

    fake_tof.set_distance(275)
    assert tof.read() == 275
    assert tof.data_ready is False  # read() consumed the flag


def test_without_int_pin_data_ready_stays_false():
    """No int_pin means no interrupt is wired, so data_ready never trips.

    Such callers use the blocking read() instead; a stray fire_irq for an
    unwired pin is a no-op.
    """
    _register_fake()
    tof = VL53L0X(sda=0, scl=1, skip_spad_info=True)
    tof.start()

    assert tof.data_ready is False
    machine.fire_irq(4)
    assert tof.data_ready is False
