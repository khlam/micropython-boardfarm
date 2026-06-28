"""MCU MicroPython firmware for the clock project.

Reads UTC date/time and position from an ATGM336H GPS over UART, derives a
local timezone offset, sets the onboard RTC, and drives the modular
display cycle on the 16x32 MAX7219 matrix.
"""

import asyncio
import os
import random
import time
from collections import namedtuple

from boot_button import button
from clock_hardware import ClockHardware
from clock_runtime import pump_gps
from machine import RTC

import clock_screens
from atgm336h import GPS
from boot_status_led import status
from clock_cycle import (
    DisplayEngine,
    hold_screen,
    play_dissolve_transition,
    play_startup_handoff,
    play_transition,
    play_wait_transition,
    run_frame_rate_test,
)
from clock_sync import ClockSynchronizer
from max7219 import MAX7219

UartWiring = namedtuple("UartWiring", ("bus_id", "tx", "rx"))
PixelSurface = namedtuple("PixelSurface", ("width_pixels", "height_pixels", "brightness"))
DisplayWiring = namedtuple(
    "DisplayWiring",
    (
        "spi_id",
        "sck",
        "mosi",
        "cs",
        "surface",
    ),
)
Board = namedtuple("Board", ("name", "uart", "display"))

_SURFACE = PixelSurface(width_pixels=32, height_pixels=16, brightness=0.1)

_machine = os.uname().machine
if "ESP32S3" in _machine:
    BOARD = Board(
        name="ESP32-S3-Zero",
        uart=UartWiring(bus_id=1, tx=13, rx=12),
        display=DisplayWiring(
            spi_id=1,
            sck=5,
            mosi=6,
            cs=7,
            surface=_SURFACE,
        ),
    )
elif "RP2350" in _machine:
    BOARD = Board(
        name="RP2350",
        uart=UartWiring(bus_id=1, tx=4, rx=5),
        display=DisplayWiring(
            spi_id=1,
            sck=10,
            mosi=11,
            cs=9,
            surface=_SURFACE,
        ),
    )
else:
    BOARD = Board(
        name="RP2040-Zero",
        uart=UartWiring(bus_id=0, tx=0, rx=1),
        display=DisplayWiring(
            spi_id=1,
            sck=26,
            mosi=27,
            cs=28,
            surface=_SURFACE,
        ),
    )

_BOOT_PAUSE_MS = 300
_INIT_ERR_PAUSE_MS = 1_000
_PROGRAM_ERR_PAUSE_MS = 200


async def clock_program(engine: object, sync: object, rng: object, clock: object) -> None:
    """Drive the screen sequence: wait for GPS, then cycle the clock faces.

    Reads top-to-bottom as the order the display actually steps through. The
    rendering mechanics live in :class:`clock_cycle.DisplayEngine`; this is only
    the sequence.
    """
    await run_frame_rate_test(engine, clock)
    regular = clock_screens.choose_regular(rng)
    target = regular if sync.synced else clock_screens.WAIT_ON
    await play_startup_handoff(engine, target, clock)

    # Wait for the first GPS fix: hold GPS / WAIT, scrolling it back into itself
    # each second until ``sync`` reports a fix, so the screen never goes blank.
    while not sync.synced:
        await hold_screen(engine, clock, stop=lambda: sync.synced)
        if sync.synced:
            break
        await play_wait_transition(engine, clock)

    # Synced: reveal a random clock, then cycle regular faces with interstitials.
    if engine.current_screen != regular:
        await play_dissolve_transition(engine, regular, clock)
    while True:
        await hold_screen(engine, clock)  # live clock face (3 min)
        await play_transition(engine, clock_screens.choose_interstitial(rng), clock)
        await hold_screen(engine, clock)  # season / full date (3 s)
        regular = clock_screens.choose_next_regular(regular, rng)
        await play_transition(engine, regular, clock)


async def guarded_program(engine: object, sync: object, rng: object, clock: object) -> None:
    """Run the screen sequence, healing the LED and restarting on any exception."""
    while True:
        try:
            await clock_program(engine, sync, rng, clock)
        except Exception:  # noqa: BLE001 — never let a render glitch kill the loop
            status.read_err()
            await asyncio.sleep_ms(_PROGRAM_ERR_PAUSE_MS)
            status.streaming()


async def run_async(gps: object, display: object, rtc: object) -> None:
    """Pump GPS and drive the display concurrently until power-off.

    Args:
        gps: Object with ``readline() -> str | None``.
        display: Object exposing ``show(frame)``.
        rtc: ``machine.RTC`` instance used as the clock source between fixes.
    """
    sync = ClockSynchronizer(rtc)
    engine = DisplayEngine(display, rtc, clock=time, rng=random, sync=sync)
    status.streaming()
    await asyncio.gather(
        pump_gps(gps, sync),
        guarded_program(engine, sync, random, time),
    )


def run(gps: object, display: object, rtc: object) -> None:
    """Start the async clock runtime. Returns only if the event loop stops."""
    asyncio.run(run_async(gps, display, rtc))


def main() -> None:
    """Run boot -> GPS/display init -> live clock loop. MicroPython entry point.

    LED sequence: white -> cyan (opening buses) -> green (running).
    On init failure: cyan -> magenta -> white (retry).
    """
    status.boot()
    time.sleep_ms(_BOOT_PAUSE_MS)

    hardware = ClockHardware(BOARD, MAX7219, GPS, RTC)
    button.on_press(hardware.flip_display)
    while True:
        status.i2c_init()
        try:
            devices = hardware.open()
        except Exception:  # noqa: BLE001
            status.init_err()
            time.sleep_ms(_INIT_ERR_PAUSE_MS)
            status.boot()
            continue
        run(devices.gps, devices.display, devices.rtc)


main()
