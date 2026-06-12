"""Host CPython tests for the pure ws2812b animation effects.

Covers the HSV helper, each effect's frame shape + animation progression, the
breathing/fade waveforms, and the brightness ceiling — all hardware-free.
"""

from ws2812b import Breathe, ColorFade, HueRotate, Rainbow, hsv_to_rgb


def test_hsv_primaries_and_extremes():
    assert hsv_to_rgb(0, 1, 1) == (255, 0, 0)
    assert hsv_to_rgb(1 / 3, 1, 1) == (0, 255, 0)
    assert hsv_to_rgb(2 / 3, 1, 1) == (0, 0, 255)
    assert hsv_to_rgb(0, 0, 1) == (255, 255, 255)  # zero saturation → white
    assert hsv_to_rgb(0.42, 1, 0) == (0, 0, 0)  # zero value → black


def test_rainbow_spreads_spectrum_and_scrolls():
    effect = Rainbow(4, brightness=1.0, step=0.25)
    first = effect.frame()
    assert len(first) == 4
    assert first[0] == (255, 0, 0)  # LED 0 at hue 0 is red
    assert len(set(first)) > 1  # different hues across the strip
    second = effect.frame()
    assert second != first  # offset advanced → frame scrolled


def test_hue_rotate_is_uniform_and_advances():
    effect = HueRotate(3, brightness=1.0, speed=0.1)
    first = effect.frame()
    assert len(first) == 3
    assert len(set(first)) == 1  # every LED shares one hue
    assert effect.frame() != first  # hue shifted


def test_breathe_starts_dark_peaks_midcycle_and_wraps():
    color = (200, 100, 50)
    effect = Breathe(2, color=color, brightness=1.0, period=4)
    f0 = effect.frame()
    assert f0 == [(0, 0, 0)] * 2  # cosine swell starts at zero
    effect.frame()  # n=1
    peak = effect.frame()  # n=2 == period/2 → full colour
    assert peak == [color] * 2
    effect.frame()  # n=3
    assert effect.frame() == f0  # frame counter wrapped back to n=0


def test_color_fade_endpoints_and_pingpong():
    start, end = (255, 0, 0), (0, 0, 255)
    effect = ColorFade(2, start=start, end=end, brightness=1.0, step=0.25)
    frames = [effect.frame() for _ in range(8)]  # one full ping-pong cycle
    assert frames[0] == [start] * 2  # t = 0
    assert frames[4] == [end] * 2  # t = 1 (far endpoint)
    assert frames[2] == frames[6]  # rising t=0.5 == falling t=0.5


def test_brightness_ceiling_caps_every_channel():
    ceiling = 0.5
    frame = Rainbow(6, brightness=ceiling, step=0.1).frame()
    assert max(max(rgb) for rgb in frame) <= int(255 * ceiling)
