"""MCU-micropython backend detecting BOOT-button edges on the RP chips' BOOTSEL.

BOOTSEL doubles as the QSPI flash CS line and has no GPIO interrupt, so a periodic
soft Timer polls rp2.bootsel_button() and reports the press edge.

RP2040 and RP2350 share this one module: BOOTSEL is wired and read identically on
both, so there is no per-chip half to split out.
"""

import rp2
from machine import Timer
from micropython import const

_POLL_MS = const(30)

# Single mutable state dict so the timer handler allocates nothing. "timer" holds
# the Timer so it keeps firing; "on_edge" is the debouncing front end in
# `button.py` that each press edge is reported to.
_state = {"timer": None, "on_edge": None, "was_down": False}


def watch_edges(on_edge: object) -> None:
    """Start a periodic soft Timer polling BOOTSEL and reporting press edges."""
    _state["on_edge"] = on_edge
    timer = Timer()
    timer.init(period=_POLL_MS, mode=Timer.PERIODIC, callback=_poll)
    _state["timer"] = timer


def _poll(_timer: object) -> None:
    """Timer handler: report one edge per press, not while the button stays held."""
    down = rp2.bootsel_button() == 1
    if down and not _state["was_down"]:
        _state["on_edge"]()
    _state["was_down"] = down
