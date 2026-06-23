"""Host CPython pytest bootstrap for the clock project firmware.

Uses the shared ``firmware_namespace`` helper to AST-load main.py with hardware
fakes injected. The firmware reads GPS NMEA sentences, sets an RTC, and renders
the selected clock face on the MAX7219 matrix.
"""

from __future__ import annotations

import os
import pathlib
import random
from collections import namedtuple
from types import SimpleNamespace

import machine
import neopixel
import pytest

from micropython_stubs.testing import firmware_namespace
from nmea import apply_parsed, nmea_checksum_valid, parse_sentence
from pixel_display import Frame
from tz_offset import offset_seconds_from_gps, utc_to_local_seconds, weekday

UartWiring = namedtuple("UartWiring", ("bus_id", "tx", "rx"))
DisplayWiring = namedtuple(
    "DisplayWiring",
    (
        "spi_id",
        "sck",
        "mosi",
        "cs",
        "width_pixels",
        "height_pixels",
        "intensity_limit",
    ),
)
Board = namedtuple("Board", ("name", "uart", "display"))

_TEST_BOARD = Board(
    name="RP2040-Zero",
    uart=UartWiring(bus_id=0, tx=0, rx=1),
    display=DisplayWiring(
        spi_id=1,
        sck=26,
        mosi=27,
        cs=28,
        width_pixels=32,
        height_pixels=16,
        intensity_limit=0.2,
    ),
)

_HERE = pathlib.Path(__file__).parent.resolve()
_FIRMWARE = _HERE.parent / "firmware" / "main.py"

_KEEP_FUNCS = {
    "emit",
    "_iso_local",
    "_rtc_datetime",
    "_parse_utc_parts",
    "_local_from_offset",
    "_gps_offset",
    "_format_time_parts",
    "_format_time_seconds",
    "_format_month_abbr",
    "_season_name",
    "_compact_glyph",
    "_compact_text_width",
    "_draw_compact_glyph",
    "_draw_compact_text_at",
    "_draw_compact_text_in_box",
    "_draw_compact_text",
    "_clock_face_frame",
    "_display_frame",
    "_wait_frame",
    "_rtc_parts",
    "_main_screen_frame",
    "_season_screen_frame",
    "_time_seconds_screen_frame",
    "_full_date_screen_frame",
    "_screen_frame_from_parts",
    "_screen_frame",
    "_screen_key_from_parts",
    "_screen_key",
    "_copy_frame",
    "_frame_value",
    "_set_frame_value",
    "_max_frame_value",
    "_min_visible_source_byte",
    "_transition_pixel_value",
    "_fade_step_value",
    "_dither_rank",
    "_masked_fade_frame",
    "_wipe_frame",
    "_scroll_frame",
    "_fade_frame",
    "_transition_frame",
    "_randbelow",
    "_choose_next_screen",
    "_choose_transition",
    "_show_wait",
    "_start_screen_cycle",
    "_start_transition",
    "_advance_transition",
    "_refresh_current_screen",
    "_refresh_display",
    "_sync_from_line",
    "run",
    "main",
}


@pytest.fixture(autouse=True)
def _reset_devices() -> None:
    """Clear machine and neopixel state between tests."""
    machine.reset()
    neopixel.reset()


@pytest.fixture
def main_ns() -> SimpleNamespace:
    """Fresh AST-loaded main.py namespace with fakes injected.

    Returns:
        SimpleNamespace with ``ns``, ``time``, and ``status`` attributes.
    """
    return firmware_namespace(
        _FIRMWARE,
        _KEEP_FUNCS,
        os=os,
        namedtuple=namedtuple,
        BOARD=_TEST_BOARD,
        apply_parsed=apply_parsed,
        nmea_checksum_valid=nmea_checksum_valid,
        parse_sentence=parse_sentence,
        Frame=Frame,
        random=random,
        offset_seconds_from_gps=offset_seconds_from_gps,
        utc_to_local_seconds=utc_to_local_seconds,
        weekday=weekday,
    )
