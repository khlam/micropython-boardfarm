"""MCU-micropython status pixel that shows the Matter device state.

``StatusLed(pixel, level)`` takes the project's NeoPixel and status brightness.
Feed it ``Node.state`` after each poll, the application's colour when it
changes, and ``fail()`` on a failed commissioning attempt; call ``tick()`` from
the loop. :mod:`matter_status_led.pattern` holds the state-to-pattern table.
"""

from matter_status_led.led import StatusLed

__all__ = ["StatusLed"]
