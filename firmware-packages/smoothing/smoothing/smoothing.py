"""MCU-micropython sliding-window smoothing functions.

A small set of pure smoothers for noisy sensor streams: simple, weighted, and
exponential moving averages plus the rolling median. Each takes the rolling
window of recent samples (oldest first, newest last) and a window size, and
returns one smoothed value.
"""

DEFAULT_WINDOW = 10


__all__ = [
    "exponential_moving_average",
    "median",
    "simple_moving_average",
    "weighted_moving_average",
]


def simple_moving_average(window: list[float], size: int = DEFAULT_WINDOW) -> float:
    """Arithmetic mean of the last `size` samples.

    Args:
        window: Recent samples, oldest first; the newest is `window[-1]`.
        size: Number of samples to average once the window has filled.

    Returns:
        The mean of the last `size` samples, or `window[-1]` while fewer than
        `size` samples are available.
    """
    if len(window) < size:
        return window[-1]
    recent = window[-size:]
    return sum(recent) / size


def weighted_moving_average(window: list[float], size: int = DEFAULT_WINDOW) -> float:
    """Linearly weighted mean of the last `size` samples, newest weighted highest.

    Weights run 1..size across the window, so the newest sample carries the most
    influence and the oldest the least — less lag than a simple average while
    still suppressing single-sample noise.

    Args:
        window: Recent samples, oldest first; the newest is `window[-1]`.
        size: Number of samples to weight once the window has filled.

    Returns:
        The weighted mean of the last `size` samples, or `window[-1]` while
        fewer than `size` samples are available.
    """
    if len(window) < size:
        return window[-1]
    recent = window[-size:]
    weighted = 0.0
    for i, value in enumerate(recent):
        weighted += (i + 1) * value
    return weighted / (size * (size + 1) / 2)


def exponential_moving_average(window: list[float], size: int = DEFAULT_WINDOW) -> float:
    """Exponential moving average over the last `size` samples.

    Smoothing factor `alpha = 2 / (size + 1)` — the standard span convention, so
    a larger window smooths more heavily. Seeded from the oldest sample in the
    window and folded forward to the newest.

    Args:
        window: Recent samples, oldest first; the newest is `window[-1]`.
        size: Span of the average once the window has filled.

    Returns:
        The EMA of the last `size` samples, or `window[-1]` while fewer than
        `size` samples are available.
    """
    if len(window) < size:
        return window[-1]
    recent = window[-size:]
    alpha = 2 / (size + 1)
    ema = recent[0]
    for value in recent[1:]:
        ema = ema + alpha * (value - ema)
    return ema


def median(window: list[float], size: int = DEFAULT_WINDOW) -> float:
    """Lower median of the last `size` samples.

    Returns the lower-middle element of the sorted window (`sorted[size // 2]`),
    which rejects single-sample spikes without averaging them in.

    Args:
        window: Recent samples, oldest first; the newest is `window[-1]`.
        size: Number of samples to rank once the window has filled.

    Returns:
        The lower median of the last `size` samples, or `window[-1]` while fewer
        than `size` samples are available.
    """
    if len(window) < size:
        return window[-1]
    recent = sorted(window[-size:])
    return recent[size // 2]
