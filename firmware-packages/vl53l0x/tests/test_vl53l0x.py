"""Host CPython pytest tests for the VL53L0X driver against the register simulator.

The simulator is faithful enough to let the driver complete init, start
continuous ranging, and return a configured distance. That's all you can
expect from a pure-register fake — it does *not* exercise NACK retries,
clock-stretch timeouts, or the ESP32-S3 bit-6 quirk. Those need hardware.
"""

import machine
from fake_vl53l0x import FakeVL53L0X
from machine import Pin, SoftI2C

from vl53l0x import VL53L0X


def test_driver_inits_with_skip_spad_info(fake_tof):
    i2c = SoftI2C(sda=Pin(0), scl=Pin(1))
    tof = VL53L0X(i2c, skip_spad_info=True, interrupt_status_mask=0x07)

    assert tof.address == 0x29
    assert tof.skip_spad_info is True


def test_read_returns_simulated_distance(fake_tof):
    i2c = SoftI2C(sda=Pin(0), scl=Pin(1))
    tof = VL53L0X(i2c, skip_spad_info=True, interrupt_status_mask=0x07)
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
    dev = FakeVL53L0X(interrupt_status_after_write=0x40)  # bit 6 only
    machine.register_device(0x29, dev)

    i2c = SoftI2C(sda=Pin(0), scl=Pin(1))
    tof = VL53L0X(i2c, skip_spad_info=True, interrupt_status_mask=0xFF)
    tof.start()
    dev.set_distance(777)
    assert tof.read() == 777
