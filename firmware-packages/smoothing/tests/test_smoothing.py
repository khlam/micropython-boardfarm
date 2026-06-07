"""Host CPython pytest for the sliding-window smoothing functions.

Pure arithmetic — no hardware or stubs. Covers, for each smoother: the
raw-until-filled gate, the computed value once the window fills, slicing to the
last `size` samples, and the default vs. custom window size.
"""

import pytest

from smoothing import (
    exponential_moving_average,
    median,
    simple_moving_average,
    weighted_moving_average,
)

_ALL = (
    simple_moving_average,
    weighted_moving_average,
    exponential_moving_average,
    median,
)


@pytest.mark.parametrize("smoother", _ALL)
def test_returns_raw_until_window_fills(smoother):
    """Below `size` samples every smoother returns the latest raw reading."""
    assert smoother([7], size=3) == 7
    assert smoother([7, 9], size=3) == 9


@pytest.mark.parametrize("smoother", _ALL)
def test_default_window_is_ten(smoother):
    """Nine samples → still raw; ten → computed (proves the default size=10)."""
    assert smoother(list(range(9))) == 8
    assert smoother(list(range(10))) != 8


def test_simple_moving_average_value():
    assert simple_moving_average([1, 2, 3], size=3) == pytest.approx(2.0)
    assert simple_moving_average([2, 4, 6, 8, 10], size=5) == pytest.approx(6.0)


def test_weighted_moving_average_value():
    # weights 1,2,3 → (1*1 + 2*2 + 3*3) / (1+2+3) = 14/6
    assert weighted_moving_average([1, 2, 3], size=3) == pytest.approx(14 / 6)


def test_exponential_moving_average_value():
    # alpha = 2/(3+1) = 0.5; 1 → 1.5 → 2.25
    assert exponential_moving_average([1, 2, 3], size=3) == pytest.approx(2.25)


def test_median_value_odd_window():
    assert median([5, 1, 3, 2, 4], size=5) == 3


def test_median_value_even_window():
    # sorted = [1, 2, 3, 4]; lower median is sorted[4 // 2] = 3
    assert median([4, 1, 3, 2], size=4) == 3


@pytest.mark.parametrize("smoother", _ALL)
def test_only_last_size_samples_are_used(smoother):
    """A stale leading sample outside the window must not affect the result."""
    short = [10.0, 20.0, 30.0]
    padded = [9999.0, *short]
    assert smoother(padded, size=3) == pytest.approx(smoother(short, size=3))
