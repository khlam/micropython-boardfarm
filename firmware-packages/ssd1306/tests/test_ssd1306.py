"""Host CPython tests for the SSD1306 framebuffer driver."""

import machine
import pytest
from fake_ssd1306 import FakeSSD1306
from ssd1306 import SSD1306, DeviceNotFoundError

ADDRESS = 0x3C


def test_constructor_opens_soft_bus_and_initialises_128_by_64_display():
    fake = _register_fake(ADDRESS)

    display = SSD1306(sda=0, scl=1)

    assert display.address == ADDRESS
    assert display.width == 128
    assert display.height == 64
    assert len(display.buffer) == 1024
    assert display.i2c.sda.id == 0
    assert display.i2c.scl.id == 1
    assert display.i2c.freq == 400_000
    assert fake.writes[-1] == b"\x40" + bytes(1024)


def test_missing_display_raises_device_not_found():
    machine.reset()

    with pytest.raises(DeviceNotFoundError, match="0x3c"):
        SSD1306(sda=0, scl=1)


def test_constructor_accepts_custom_address():
    custom_address = 0x3D
    _register_fake(custom_address)

    display = SSD1306(sda=4, scl=5, address=custom_address)

    assert display.address == custom_address


def test_initialisation_sends_expected_command_sequence():
    fake = _register_fake(ADDRESS)

    SSD1306(sda=0, scl=1)

    commands = [write[1] for write in fake.writes if len(write) == 2 and write[0] == 0x80]
    assert commands[:25] == [
        0xAE,
        0x20,
        0x00,
        0x40,
        0xA1,
        0xA8,
        0x3F,
        0xC8,
        0xD3,
        0x00,
        0xDA,
        0x12,
        0xD5,
        0x80,
        0xD9,
        0xF1,
        0xDB,
        0x30,
        0x81,
        0xFF,
        0xA4,
        0xA6,
        0x8D,
        0x14,
        0xAF,
    ]


def test_text_and_show_flush_nonempty_framebuffer():
    fake = _register_fake(ADDRESS)
    display = SSD1306(sda=0, scl=1)

    display.fill(0)
    display.text("Hello world", 0, 0, 1)
    display.show()

    assert fake.writes[-1][0] == 0x40
    assert len(fake.writes[-1]) == 1025
    assert any(fake.writes[-1][1:])


def test_invalid_height_is_rejected_before_opening_bus():
    machine.reset()

    with pytest.raises(ValueError, match="divisible by 8"):
        SSD1306(sda=0, scl=1, height=63)


def _register_fake(address: int) -> FakeSSD1306:
    """Reset machine state and register a display fake at ``address``."""
    machine.reset()
    fake = FakeSSD1306()
    machine.register_device(address, fake)
    return fake
