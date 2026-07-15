"""Host CPython pytest tests for run() in led-effects firmware.

Covers the emit-then-render cadence, frame shape and colour range, and the
endless effect-cycle wrap-around, with FRAMES_PER_EFFECT shrunk via the exec
namespace so tests stay fast.
"""

import io
import json
import os
import pathlib
from collections import namedtuple
from contextlib import redirect_stdout

import pytest

from micropython_stubs.testing import StopLoopError, firmware_namespace
from ws2812b import Breathe, ColorFade, HueRotate, Rainbow

_FIRMWARE = pathlib.Path(__file__).parent.parent / "firmware" / "main.py"
_KEEP_FUNCS = {"emit", "build_effects", "run"}


def test_run_emits_effect_name_then_renders_each_frame():
    main_ns = _make_main_ns()
    strip = _FakeStrip(renders=5)
    lines = _run_effects(main_ns, strip, frames_per_effect=2)
    assert [ln["effect"] for ln in lines] == ["rainbow", "hue_rotate", "breathe"]
    led_count = main_ns.ns["LED_COUNT"]
    assert all(len(frame) == led_count for frame in strip.frames)
    assert all(0 <= c <= 255 for frame in strip.frames for rgb in frame for c in rgb)


def test_run_cycles_back_to_first_effect():
    main_ns = _make_main_ns()
    strip = _FakeStrip(renders=4)
    lines = _run_effects(main_ns, strip, frames_per_effect=1)
    assert [ln["effect"] for ln in lines] == [
        "rainbow",
        "hue_rotate",
        "breathe",
        "color_fade",
        "rainbow",
    ]


def _make_main_ns():
    """Create a fresh AST-loaded main.py namespace with fakes."""
    return firmware_namespace(
        _FIRMWARE,
        _KEEP_FUNCS,
        os=os,
        namedtuple=namedtuple,
        Breathe=Breathe,
        ColorFade=ColorFade,
        HueRotate=HueRotate,
        Rainbow=Rainbow,
    )


def _run_effects(main_ns, strip, frames_per_effect):
    """Drive run() until the strip's render budget raises StopLoopError."""
    main_ns.ns["FRAMES_PER_EFFECT"] = frames_per_effect
    buf = io.StringIO()
    with redirect_stdout(buf), pytest.raises(StopLoopError):
        main_ns.ns["run"](strip, main_ns.ns["build_effects"]())
    return [json.loads(line) for line in buf.getvalue().splitlines() if line.strip()]


class _FakeStrip:
    """Records rendered frames; raises StopLoopError once the budget is spent."""

    def __init__(self, renders) -> None:
        self._budget = renders
        self.frames = []

    def render(self, frame):
        if len(self.frames) >= self._budget:
            raise StopLoopError
        self.frames.append(list(frame))
