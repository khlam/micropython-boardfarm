"""Host CPython smoke test: boot led-clock firmware/main.py and count one full cycle.

Only the hardware boundary is faked: machine and neopixel come from
micropython_stubs, boot_status_led is a FakeStatus, and time.sleep_ms raises
StopLoopError on a chosen step to escape the endless count.
"""

import io
import pathlib
import sys
from contextlib import redirect_stdout
from types import SimpleNamespace

import neopixel
import pytest

from micropython_stubs.testing import FakeStatus, StopLoopError, json_lines, load_firmware_module

_FIRMWARE = pathlib.Path(__file__).parent.parent / "firmware" / "main.py"
_GREEN = (0, 64, 0)
_OFF = (0, 0, 0)

# A seven-segment 1 lights only the two right-hand bars. The wired chain
# (a b c d e f g) puts the upper right first (LEDs 0-1) and the lower right
# sixth (LEDs 10-11). The 11th step wraps back to 0 after 9; the 12th shows 1.
_ONE = [_GREEN] * 2 + [_OFF] * 8 + [_GREEN] * 2 + [_OFF] * 2
_CASES = [
    pytest.param(12, [*range(10), 0, 1], _ONE, id="zero_to_nine_then_wrap"),
]


class _StepTime:
    """`time` stand-in whose sleep_ms raises StopLoopError on the last step."""

    def __init__(self, steps: int) -> None:
        self._steps = steps

    def sleep_ms(self, _ms: int) -> None:
        self._steps -= 1
        if self._steps == 0:
            raise StopLoopError


@pytest.mark.parametrize(("steps", "digits", "final_frame"), _CASES)
def test_main_counts_digits_on_the_chain(monkeypatch, steps, digits, final_frame):
    fake_status = FakeStatus()
    neopixel.reset()
    monkeypatch.syspath_prepend(str(_FIRMWARE.parent))
    monkeypatch.setitem(sys.modules, "time", _StepTime(steps))
    monkeypatch.setitem(sys.modules, "boot_status_led", SimpleNamespace(status=fake_status))
    module = load_firmware_module(_FIRMWARE, "led_clock_main", "main")

    buf = io.StringIO()
    with redirect_stdout(buf), pytest.raises(StopLoopError):
        module.main()

    (chain,) = neopixel.NeoPixel.instances
    assert (chain.pin.id, chain.n) == (15, 14)
    assert [chain[i] for i in range(chain.n)] == final_frame
    assert [line["digit"] for line in json_lines(buf.getvalue())] == digits
    assert fake_status.calls == ["boot", "streaming"]
