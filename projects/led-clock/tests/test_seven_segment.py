"""Host CPython tests for digit_frame() in the led-clock seven_segment module.

Rows use the board's real chain order (a b c d e f g, two LEDs per segment).
That chain enters at the upper right, runs counterclockwise round the outside,
and ends on the middle, so the LED indices sit at: 0,1 upper right; 2,3 top;
4,5 upper left; 6,7 lower left; 8,9 bottom; 10,11 lower right; 12,13 middle.
Expected lit sets are the usual seven-segment digit shapes drawn on those
positions.
"""

import pathlib
import sys
from contextlib import nullcontext

import pytest

_FIRMWARE_DIR = str(pathlib.Path(__file__).parent.parent / "firmware")
if _FIRMWARE_DIR not in sys.path:
    sys.path.insert(0, _FIRMWARE_DIR)

from seven_segment import digit_frame  # noqa: E402

_CHAIN_ORDER = "abcdefg"
_LEDS_PER_SEGMENT = 2
_LED_COUNT = 14
_ON = (0, 64, 0)
_OFF = (0, 0, 0)
_OK = nullcontext()

_CASES = [
    pytest.param(0, set(range(12)), _OK, id="0"),
    pytest.param(1, {0, 1, 10, 11}, _OK, id="1"),
    pytest.param(2, {0, 1, 2, 3, 6, 7, 8, 9, 12, 13}, _OK, id="2"),
    pytest.param(3, {0, 1, 2, 3, 8, 9, 10, 11, 12, 13}, _OK, id="3"),
    pytest.param(4, {0, 1, 4, 5, 10, 11, 12, 13}, _OK, id="4"),
    pytest.param(5, {2, 3, 4, 5, 8, 9, 10, 11, 12, 13}, _OK, id="5"),
    pytest.param(6, {2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13}, _OK, id="6"),
    pytest.param(7, {0, 1, 2, 3, 10, 11}, _OK, id="7"),
    pytest.param(8, set(range(14)), _OK, id="8"),
    pytest.param(9, {0, 1, 2, 3, 4, 5, 8, 9, 10, 11, 12, 13}, _OK, id="9"),
    pytest.param(-1, set(), pytest.raises(ValueError, match="0-9"), id="below_range"),
    pytest.param(10, set(), pytest.raises(ValueError, match="0-9"), id="above_range"),
]


@pytest.mark.parametrize(("digit", "lit", "outcome"), _CASES)
def test_digit_frame(digit, lit, outcome):
    with outcome:
        frame = digit_frame(
            digit,
            chain_order=_CHAIN_ORDER,
            leds_per_segment=_LEDS_PER_SEGMENT,
            on=_ON,
            off=_OFF,
        )
        assert frame == [_ON if i in lit else _OFF for i in range(_LED_COUNT)]
