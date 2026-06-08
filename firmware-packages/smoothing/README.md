# smoothing

Pure sliding-window smoothing functions for noisy sensor streams, shared across
all MCUs. No hardware dependency — just arithmetic over a window of recent
samples.

## Layout
```
smoothing/
  smoothing/
    __init__.py     re-exports the four smoothers
    smoothing.py    the functions
  tests/            host pytest, pure-arithmetic
```

## Public API
```python
from smoothing import (
    simple_moving_average,
    weighted_moving_average,
    exponential_moving_average,
    median,
)

window = []
for sample in stream:
    window.append(sample)
    if len(window) > 10:          # keep the window bounded to `size`
        del window[0]
    smoothed = simple_moving_average(window, 10)
```

Each function takes the rolling window (oldest first, newest last) and a window
`size` (default `10`), and returns one smoothed value:

| Function | Behaviour once the window has filled |
| --- | --- |
| `simple_moving_average` | arithmetic mean of the last `size` samples |
| `weighted_moving_average` | linearly weighted mean, newest sample weighted highest |
| `exponential_moving_average` | EMA with `alpha = 2 / (size + 1)` (the span convention) |
| `median` | lower median (`sorted[size // 2]`) — rejects single-sample spikes |

## Notes
- **Raw until filled.** While the window holds fewer than `size` samples, every
  function returns the latest raw reading (`window[-1]`) unchanged, so a freshly
  started stream isn't biased by a half-full window.
- **Stateless and pure.** The functions never mutate the window; the caller owns
  the buffer and is responsible for appending each new sample and trimming it to
  `size`. This keeps memory bounded on the MCU and the functions trivially
  testable.
- The window must hold at least one sample. Calling with an empty window is a
  caller bug and raises `IndexError`.

## Tests
From the repo root:
```
docker compose run --rm --build pytest -- /firmware-packages/smoothing/tests
```
Coverage is logic-only: raw-until-filled gating, the computed value of each
smoother once the window fills, window slicing to the last `size` samples, and
the default vs. custom window size.
