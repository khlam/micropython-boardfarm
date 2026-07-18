from effects import Breathe, ColorFade, HueRotate, Rainbow, hsv_to_rgb


def test_hsv_primaries_and_extremes():
    assert hsv_to_rgb(0, 1, 1) == (255, 0, 0)
    assert hsv_to_rgb(1 / 3, 1, 1) == (0, 255, 0)
    assert hsv_to_rgb(2 / 3, 1, 1) == (0, 0, 255)
    assert hsv_to_rgb(0, 0, 1) == (255, 255, 255)
    assert hsv_to_rgb(0.42, 1, 0) == (0, 0, 0)


def test_hsv_wraps_negative_hue():
    wrapped = hsv_to_rgb(-0.1, 1, 1)
    assert wrapped == hsv_to_rgb(0.9, 1, 1)
    assert all(0 <= channel <= 255 for channel in wrapped)


def test_rainbow_spreads_spectrum_and_scrolls():
    effect = Rainbow(4, brightness=1.0, step=0.25)
    first = effect.frame()
    assert len(first) == 4
    assert first[0] == (255, 0, 0)
    assert len(set(first)) > 1
    assert effect.frame() != first


def test_hue_rotate_is_uniform_and_advances():
    effect = HueRotate(3, brightness=1.0, speed=0.1)
    first = effect.frame()
    assert len(first) == 3
    assert len(set(first)) == 1
    assert effect.frame() != first


def test_breathe_starts_dark_peaks_midcycle_and_wraps():
    color = (200, 100, 50)
    effect = Breathe(2, color=color, brightness=1.0, period=4)
    first = effect.frame()
    assert first == [(0, 0, 0)] * 2
    effect.frame()
    assert effect.frame() == [color] * 2
    effect.frame()
    assert effect.frame() == first


def test_color_fade_endpoints_and_pingpong():
    start, end = (255, 0, 0), (0, 0, 255)
    effect = ColorFade(2, start=start, end=end, brightness=1.0, step=0.25)
    frames = [effect.frame() for _ in range(8)]
    assert frames[0] == [start] * 2
    assert frames[4] == [end] * 2
    assert frames[2] == frames[6]


def test_brightness_ceiling_caps_every_channel():
    ceiling = 0.5
    frame = Rainbow(6, brightness=ceiling, step=0.1).frame()
    assert max(max(rgb) for rgb in frame) <= int(255 * ceiling)
