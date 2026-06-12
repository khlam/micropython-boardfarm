"""Host CPython tests for the ws2812b Strip driver and chip dispatch.

Each chip backend wires the right data pin, the dispatcher picks the matching
module, and `render()` buffers a whole frame to the NeoPixel stub and latches it.
"""

import importlib

import machine
import neopixel
import pytest

# (os.uname().machine token, expected backend module, expected data pin).
CHIP_BACKENDS = [
    ("RP2040", "ws2812b.rp2040", 15),
    ("RP2350", "ws2812b.rp2350", 15),
    ("ESP32S3", "ws2812b.esp32s3", 15),
]


@pytest.mark.parametrize("chip,backend_mod,pin", CHIP_BACKENDS, indirect=["chip"])
def test_dispatch_picks_correct_backend(chip, backend_mod, pin, strip_module):
    assert strip_module._pixels.__module__ == backend_mod


@pytest.mark.parametrize("chip,backend_mod,pin", CHIP_BACKENDS, indirect=["chip"])
def test_strip_constructs_neopixel_on_chip_data_pin(chip, backend_mod, pin, strip_module):
    strip_module.Strip(8)
    assert machine.pin_constructions[-1] == (pin, "OUT")
    assert neopixel.NeoPixel.instances[-1].n == 8


@pytest.mark.parametrize("chip,backend_mod,pin", CHIP_BACKENDS, indirect=["chip"])
def test_render_writes_frame_to_strip(chip, backend_mod, pin, strip_module):
    strip = strip_module.Strip(3)
    frame = [(10, 20, 30), (40, 50, 60), (70, 80, 90)]
    strip.render(frame)
    np = neopixel.NeoPixel.instances[-1]
    assert [np[i] for i in range(3)] == frame  # whole strip buffered
    assert len(np.writes) == 1  # latched exactly once
    assert np.writes[-1] == frame[0]  # stub records LED 0 on write


@pytest.fixture
def strip_module(chip):
    """Re-import ws2812b.strip after `chip` patches os.uname."""
    return importlib.import_module("ws2812b.strip")
