"""Host CPython pytest tests for the SSD1306 driver against the register simulator.

Covers the geometry-dependent init sequence, MONO_VLSB pixel addressing,
the bulk fill paths, out-of-bounds clamping, and the address-window framing
that show() emits. Silicon timing (charge-pump ramp, NACK) is out of scope.
"""

import machine
import pytest
from fake_ssd1306 import FakeSSD1306

from ssd1306 import OLED_ADDRS, SSD1306, ScreenSize


def test_oled_addrs_contains_default_and_alternate():
    assert 0x3C in OLED_ADDRS
    assert 0x3D in OLED_ADDRS


def test_screen_size_values():
    assert ScreenSize.RES_128x32 == (128, 32)
    assert ScreenSize.RES_128x64 == (128, 64)


@pytest.mark.parametrize(
    "size, expected_ms",
    [(ScreenSize.RES_128x32, 16), (ScreenSize.RES_128x64, 33)],
)
def test_frame_ms_matches_panel_height(size, expected_ms):
    assert ScreenSize.frame_ms(size) == expected_ms


def test_init_turns_display_on(fake_oled):
    SSD1306(_make_i2c(), 128, 64)
    assert 0xAF in fake_oled.commands  # display-on command issued


def test_init_sets_multiplex_for_height(fake_oled):
    SSD1306(_make_i2c(), 128, 64)
    assert (0xA8, 63) in fake_oled.command_writes


@pytest.mark.parametrize(
    "height, com_pins",
    [(64, 0x12), (32, 0x02)],
)
def test_init_com_pins_track_geometry(height, com_pins):
    dev = FakeSSD1306(width=128, height=height)
    machine.register_device(0x3C, dev)
    SSD1306(_make_i2c(), 128, height)
    assert (0xDA, com_pins) in dev.command_writes


def test_init_clears_then_flushes(fake_oled):
    SSD1306(_make_i2c(), 128, 64)
    # Init ends with fill(0) + show(): GDDRAM flushed once and all-zero.
    assert fake_oled.show_count == 1
    assert set(fake_oled.gddram) == {0}


def test_pixel_sets_correct_bit(fake_oled):
    oled = SSD1306(_make_i2c(), 128, 64)
    oled.pixel(0, 0, 1)
    oled.pixel(5, 9, 1)  # page 1, bit 1
    oled.show()
    assert fake_oled.pixel(0, 0) == 1
    assert fake_oled.pixel(5, 9) == 1
    assert fake_oled.pixel(1, 0) == 0


def test_pixel_clear(fake_oled):
    oled = SSD1306(_make_i2c(), 128, 64)
    oled.pixel(3, 3, 1)
    oled.pixel(3, 3, 0)
    oled.show()
    assert fake_oled.pixel(3, 3) == 0


def test_fill_on_then_off(fake_oled):
    oled = SSD1306(_make_i2c(), 128, 64)
    oled.fill(1)
    oled.show()
    assert set(fake_oled.gddram) == {0xFF}
    oled.fill(0)
    oled.show()
    assert set(fake_oled.gddram) == {0x00}


@pytest.mark.parametrize("coord", [(-1, 0), (128, 0), (0, -1), (0, 64)])
def test_pixel_out_of_bounds_is_noop(fake_oled, coord):
    oled = SSD1306(_make_i2c(), 128, 64)
    oled.pixel(*coord, 1)
    oled.show()
    assert set(fake_oled.gddram) == {0}  # nothing lit


def test_show_emits_address_windows(fake_oled):
    oled = SSD1306(_make_i2c(), 128, 64)
    fake_oled.command_writes.clear()
    oled.show()
    assert (0x21, 0, 127) in fake_oled.command_writes  # column window
    assert (0x22, 0, 7) in fake_oled.command_writes  # page window


def _make_i2c():
    return machine.I2C(0, sda=machine.Pin(0), scl=machine.Pin(1))
