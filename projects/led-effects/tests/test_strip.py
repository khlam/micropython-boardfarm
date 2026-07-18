import machine
import neopixel
from strip import Strip


def test_strip_constructs_neopixel_on_given_pin():
    Strip(8, pin=15)
    assert machine.pin_constructions[-1] == (15, "OUT")
    assert neopixel.NeoPixel.instances[-1].n == 8


def test_render_writes_frame_to_strip():
    strip = Strip(3, pin=15)
    frame = [(10, 20, 30), (40, 50, 60), (70, 80, 90)]
    strip.render(frame)
    np = neopixel.NeoPixel.instances[-1]
    assert [np[i] for i in range(3)] == frame
    assert len(np.writes) == 1
    assert np.writes[-1] == frame[0]
