"""MCU-micropython sliding-window smoothing functions (SMA, WMA, EMA, median)."""

from smoothing.smoothing import (
    exponential_moving_average,
    median,
    simple_moving_average,
    weighted_moving_average,
)

__all__ = [
    "exponential_moving_average",
    "median",
    "simple_moving_average",
    "weighted_moving_average",
]
