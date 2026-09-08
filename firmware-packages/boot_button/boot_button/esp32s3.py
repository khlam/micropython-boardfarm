"""MCU-micropython backend detecting ESP32-S3-Zero BOOT-button edges on GPIO0 via an IRQ."""

from machine import Pin

# Single mutable state dict so the hard-IRQ handler allocates nothing. "button"
# holds the Pin so its IRQ isn't garbage-collected; "on_edge" is the debouncing
# front end in `button.py` that each press edge is reported to.
_state = {"button": None, "on_edge": None}


def watch_edges(on_edge: object) -> None:
    """Wire a falling-edge IRQ on GPIO0 to report press edges to `on_edge`."""
    _state["on_edge"] = on_edge
    button = Pin(0, Pin.IN, Pin.PULL_UP)
    button.irq(trigger=Pin.IRQ_FALLING, handler=_isr)
    _state["button"] = button


def _isr(_pin: object) -> None:
    """Hard-IRQ handler: report one press edge."""
    _state["on_edge"]()
