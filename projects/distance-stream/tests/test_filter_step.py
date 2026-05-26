"""Host CPython pytest tests for the median-of-5 + EMA helper in distance-stream main.py.

Exercises `_filter_step` in isolation from the streaming loop's I/O and
recovery paths. Four safety properties under test:
  - median-of-5 rejects single-sample glitches that slip past the
    out-of-range gate (i.e. any spike below OUT_OF_RANGE_MM);
  - EMA (alpha = 0.1) converges toward the rolling median;
  - every in-range sample produces an integer output and updates state;
  - the rolling median window caps at MEDIAN_N entries (FIFO eviction).
"""

import pytest


def test_first_sample_seeds_ema_to_itself(filter_step):
    out, buf, ema = filter_step(412, [], None)
    assert out == 412
    assert buf == [412]
    assert ema == 412


def test_median_rejects_single_in_range_spike(filter_step):
    # An in-range spike (e.g. 800 mm amid a steady 100 mm stream) reaches the
    # filter — only readings >= OUT_OF_RANGE_MM are stripped upstream. The
    # median should pick a neighbour, leaving the EMA undisturbed.
    out, _, ema = filter_step(800, [100, 100, 100, 100], 100.0)
    assert out == 100
    assert ema == 100.0


def test_median_window_caps_at_five(main_ns, filter_step):
    median_n = main_ns.ns["MEDIAN_N"]
    buf: list[int] = []
    ema: float | None = None
    for distance_mm in (100, 101, 102, 103, 104, 105, 106):
        _, buf, ema = filter_step(distance_mm, buf, ema)
    assert len(buf) == median_n == 5
    assert buf == [102, 103, 104, 105, 106]


def test_ema_converges_to_constant_input(filter_step):
    # Stale ema=100 driven by a saturated median of 200: the (1 - alpha)^k
    # residual decays geometrically. After 100 steps it's well under 1 mm.
    buf = [200, 200, 200, 200, 200]
    ema: float | None = 100.0
    out = None
    for _ in range(100):
        out, buf, ema = filter_step(200, buf, ema)
    assert out == 200


def test_ema_alpha_one_step_response(filter_step):
    # Pins alpha = 0.1 exactly: buf saturated at 200 -> median = 200,
    # ema_new = 100 * 0.9 + 200 * 0.1 = 110.
    out, _, ema = filter_step(200, [200, 200, 200, 200, 200], 100.0)
    assert ema == pytest.approx(110.0)
    assert out == 110


def test_just_below_out_of_range_is_kept(main_ns, filter_step):
    distance_mm = main_ns.ns["OUT_OF_RANGE_MM"] - 1
    out, buf, ema = filter_step(distance_mm, [], None)
    assert out == distance_mm
    assert buf == [distance_mm]
    assert ema == distance_mm


@pytest.fixture
def filter_step(main_ns):
    return main_ns.ns["_filter_step"]
