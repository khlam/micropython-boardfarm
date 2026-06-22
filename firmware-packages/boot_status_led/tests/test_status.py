"""Host CPython pytest tests for the LED state machine.

Each named transition calls `_show` with the right colour, and each chip
backend wires the right pin / scales correctly.
"""

import importlib
import os
import sys

import machine
import neopixel
import pytest


def _reset_stubs():
    """Clear shared stub state and cached imports."""
    machine.reset()
    neopixel.reset()
    for mod in list(sys.modules):
        if mod.startswith("boot_status_led"):
            del sys.modules[mod]


@pytest.mark.parametrize(
    "chip,backend_mod",
    [
        ("RP2040", "boot_status_led.rp2040"),
        ("RP2350", "boot_status_led.rp2350"),
        ("ESP32S3", "boot_status_led.esp32s3"),
    ],
)
def test_status_dispatch_picks_correct_backend(chip, backend_mod, monkeypatch):
    _reset_stubs()

    class _Uname:
        machine = chip

    monkeypatch.setattr(os, "uname", _Uname)
    status_module = importlib.import_module("boot_status_led.status")
    assert status_module._show.__module__ == backend_mod


def test_rp2040_backend_scales_brightness():
    _reset_stubs()
    os.uname = type("U", (), {"machine": "RP2040 with RP2040"})
    status_module = importlib.import_module("boot_status_led.status")

    status_module.streaming()
    # BRIGHTNESS=0.1 → green (0, 255, 0) → (0, 25, 0).
    assert neopixel.NeoPixel.instances[0].writes[-1] == (0, 25, 0)


def test_rp2350_backend_collapses_to_on_off():
    _reset_stubs()
    os.uname = type("U", (), {"machine": "RP2350 with RP2350"})
    status_module = importlib.import_module("boot_status_led.status")
    rp2350 = importlib.import_module("boot_status_led.rp2350")

    status_module.streaming()
    assert rp2350._led.value() == 1  # green → on

    status_module.read_err()
    assert rp2350._led.value() == 0  # red is not green → off


def test_esp32s3_backend_scales_brightness():
    _reset_stubs()
    os.uname = type("U", (), {"machine": "Generic ESP32S3 module with ESP32S3"})
    status_module = importlib.import_module("boot_status_led.status")

    status_module.streaming()
    # BRIGHTNESS=0.1 → green (0, 255, 0) → (0, 25, 0).
    assert neopixel.NeoPixel.instances[0].writes[-1] == (0, 25, 0)


@pytest.mark.parametrize(
    "transition,expected",
    [
        ("boot", (255, 255, 255)),
        ("i2c_init", (0, 255, 255)),
        ("no_device", (255, 128, 0)),
        ("init_err", (255, 0, 255)),
    ],
)
def test_named_transitions_write_expected_colour(transition, expected):
    _reset_stubs()
    os.uname = type("U", (), {"machine": "RP2040 with RP2040"})
    status_module = importlib.import_module("boot_status_led.status")

    getattr(status_module, transition)()
    scaled = tuple(int(c * 0.1) for c in expected)
    assert neopixel.NeoPixel.instances[0].writes[-1] == scaled
