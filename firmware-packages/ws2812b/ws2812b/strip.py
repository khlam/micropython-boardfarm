"""MCU-micropython WS2812B strip driver with chip-dispatched data pin.

Picks the per-chip backend at import time (the pattern ``boot_status_led``
establishes), so project firmware constructs ``Strip(count)`` without knowing
which board it runs on. The backend owns the one chip-specific detail — the
WS2812B data GPIO — and the effects in ``ws2812b.effects`` stay hardware-free.
"""

import os

# Pick the chip-specific backend at import time.
_machine = os.uname().machine
if "ESP32S3" in _machine:
    from ws2812b.esp32s3 import pixels as _pixels
elif "RP2350" in _machine:
    from ws2812b.rp2350 import pixels as _pixels
else:
    from ws2812b.rp2040 import pixels as _pixels


class Strip:
    """Owns a NeoPixel buffer and latches effect frames to the WS2812B LEDs."""

    def __init__(self, count: int) -> None:
        """Build a ``count``-LED strip on the active chip's data pin."""
        self.count = count
        self._np = _pixels(count)

    def render(self, frame: list[tuple[int, int, int]]) -> None:
        """Write one ``frame`` (one ``(r, g, b)`` per LED) to the strip and latch it.

        Args:
            frame: ``count`` colour tuples, as produced by an effect's
                ``frame()``; index ``i`` lights LED ``i``.
        """
        for i in range(self.count):
            self._np[i] = frame[i]
        self._np.write()
