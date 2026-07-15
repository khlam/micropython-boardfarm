"""Host CPython tests for the ws2812b Strip driver.

The constructor builds the NeoPixel on the caller-supplied data pin, and
`render()` buffers a whole frame to the NeoPixel stub and latches it once.
"""

import machine
import neopixel

from ws2812b import Strip


def test_strip_constructs_neopixel_on_given_pin():
    Strip(8, pin=15)
    assert machine.pin_constructions[-1] == (15, "OUT")
    assert neopixel.NeoPixel.instances[-1].n == 8


def test_render_writes_frame_to_strip():
    strip = Strip(3, pin=15)
    frame = [(10, 20, 30), (40, 50, 60), (70, 80, 90)]
    strip.render(frame)
    np = neopixel.NeoPixel.instances[-1]
    assert [np[i] for i in range(3)] == frame  # whole strip buffered
    assert len(np.writes) == 1  # latched exactly once
    assert np.writes[-1] == frame[0]  # stub records LED 0 on write
