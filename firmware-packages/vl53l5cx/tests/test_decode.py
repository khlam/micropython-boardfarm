"""Host CPython tests for the VL53L5CX pure byte-decode helpers.

These static methods turn raw sensor block bytes into Python values and need no
I²C, so they are unit-tested directly against crafted big-endian inputs.
"""

import struct

from vl53l5cx.vl53l5cx import VL53L5CX


def test_header_unpacks_type_size_index():
    bh = (0xD33C << 16) | (0x40 << 4) | 0x2
    assert VL53L5CX._header(bh) == (0x2, 0x40, 0xD33C)


def test_swap_buffer_reverses_each_4byte_word():
    buf = bytearray([0, 1, 2, 3, 4, 5, 6, 7])
    VL53L5CX._swap_buffer(buf)
    assert bytes(buf) == bytes([3, 2, 1, 0, 7, 6, 5, 4])


def test_distance_mm_shifts_right_two():
    raw = struct.pack(">4h", 400, 800, 1200, 2000)
    assert VL53L5CX._distance_mm(raw) == [100, 200, 300, 500]


def test_distance_mm_clamps_negative_to_zero():
    raw = struct.pack(">3h", -4, -2000, 40)
    assert VL53L5CX._distance_mm(raw) == [0, 0, 10]


def test_ambient_per_spad_floor_divides_by_2048():
    raw = struct.pack(">3I", 2048, 4096, 3000)
    assert VL53L5CX._ambient_per_spad(raw) == [1, 2, 1]


def test_nb_spads_enabled_unpacks_uint32():
    raw = struct.pack(">3I", 10, 20, 4_000_000_000)
    assert VL53L5CX._nb_spads_enabled(raw) == [10, 20, 4_000_000_000]


def test_range_sigma_mm_divides_by_128():
    raw = struct.pack(">2H", 128, 320)
    assert VL53L5CX._range_sigma_mm(raw) == [1.0, 2.5]


def test_signal_per_spad_divides_by_2048():
    raw = struct.pack(">2I", 2048, 1024)
    assert VL53L5CX._signal_per_spad(raw) == [1.0, 0.5]


def test_motion_indicator_unpacks_header_and_32_zones():
    raw = struct.pack(">IIBBBB32I", 7, 9, 1, 2, 3, 4, *range(32))
    decoded = VL53L5CX._motion_indicator(raw)
    assert decoded[:6] == (7, 9, 1, 2, 3, 4)
    assert decoded[6:] == tuple(range(32))
