"""MCU-micropython firmware for the clock project.

Reads UTC date/time + longitude from an ATGM336H GPS over UART (NMEA), derives a
fixed local-time offset from the longitude, sets the onboard RTC, and drives an
8x32 MAX7219 LED matrix over SPI. UART and SPI are independent buses, so a single
cooperative loop pumps the GPS (non-blocking ``readline``) and advances the
display every iteration — the RTC keeps time between GPS bursts, so neither bus
blocks the other.

The display alternates the local time (12-hour, bold, blinking colon, AM/PM) and
the current day of the week; see the max7219 DisplayCycle.
"""

import time

import ujson
from machine import RTC

from atgm336h import connect as gps_connect
from boot_status_led import status
from max7219 import DisplayCycle, day_name
from max7219 import connect as display_connect
from nmea import nmea_checksum_valid, parse_sentence
from tz_offset import local_from_gps, offset_hours_from_longitude

_WAIT_TEXT = "WAITING FOR GPS"
_LOOP_MS = 10
_WIGGLE_MS = 120
_BOOT_PAUSE_MS = 300
_INIT_ERR_PAUSE_MS = 1_000


def emit(obj: dict) -> None:
    """Print one line of compact JSON to the serial port.

    All firmware output must go through this helper; raw ``print()`` calls
    elsewhere pollute the serial stream and are silently dropped by the viz
    JSON parser.
    """
    print(ujson.dumps(obj))


def _apply_line(line: str, rtc: object) -> dict | None:
    """Set the RTC from one NMEA line and return a status payload, or None.

    Acts only on a checksum-valid RMC sentence (the one ATGM336H sentence that
    carries UTC time, date, and longitude together). Other sentences return
    None so the caller leaves the RTC untouched.

    Args:
        line: A raw NMEA sentence including its ``*HH`` checksum.
        rtc: A ``machine.RTC``; its ``datetime()`` is set to local time.

    Returns:
        A dict describing the new local time (for ``emit``), or None when the
        line is not a usable fix.
    """
    if not nmea_checksum_valid(line):
        return None
    *_, parsed = parse_sentence(line)
    if "utc" not in parsed or "date" not in parsed or "lon" not in parsed:
        return None
    year, month, day, wd, hour, minute, second = local_from_gps(
        parsed["date"], parsed["utc"], parsed["lon"]
    )
    rtc.datetime((year, month, day, wd, hour, minute, second, 0))
    return {
        "fix": True,
        "lon": parsed["lon"],
        "offset_h": offset_hours_from_longitude(parsed["lon"]),
        "local": f"{year:04d}-{month:02d}-{day:02d}T{hour:02d}:{minute:02d}:{second:02d}",
        "day": day_name(wd),
    }


def _read_payload(gps: object, rtc: object) -> dict | None:
    """Read one GPS line and apply it to the RTC; return the payload or None."""
    line = gps.readline()
    if line is None:
        return None
    return _apply_line(line, rtc)


def _advance_display(display: object, cycle: object, *, have_fix: bool, wiggle_tick: int) -> int:
    """Update the display for one loop tick and return the next wiggle tick.

    Once a fix is acquired the DisplayCycle owns the display; before that, the
    "waiting for GPS" placeholder is wiggled so the panel shows it is alive.

    Args:
        display: The MAX7219 instance.
        cycle: The DisplayCycle instance.
        have_fix: Whether a GPS fix has set the RTC yet.
        wiggle_tick: ``ticks_ms`` of the last placeholder wiggle.

    Returns:
        The wiggle tick to carry into the next iteration.
    """
    if have_fix:
        cycle.step()
        return wiggle_tick
    now = time.ticks_ms()
    if time.ticks_diff(now, wiggle_tick) >= _WIGGLE_MS:
        display.wiggle_step()
        return now
    return wiggle_tick


def run(gps: object, display: object) -> None:
    """Pump GPS and drive the display forever in one cooperative loop.

    Args:
        gps: An object with ``readline() -> str | None`` (ATGM336H wrapper).
        display: A MAX7219 instance.
    """
    rtc = RTC()
    cycle = DisplayCycle(display, rtc)
    have_fix = False
    display.show_auto(_WAIT_TEXT)
    wiggle_tick = time.ticks_ms()
    status.streaming()
    while True:
        try:
            payload = _read_payload(gps, rtc)
        except Exception:  # noqa: BLE001 — a stray sensor/UART fault must not kill the loop
            status.read_err()
            emit({"diag": "read_err"})
            status.streaming()
            payload = None
        if payload is not None:
            payload["t"] = time.ticks_ms()
            emit(payload)
            if not have_fix:
                have_fix = True
                cycle.start()
        wiggle_tick = _advance_display(display, cycle, have_fix=have_fix, wiggle_tick=wiggle_tick)
        time.sleep_ms(_LOOP_MS)


def main() -> None:
    """Run boot → GPS/display init → loop. MicroPython entry point.

    LED sequence: white → cyan (opening buses) → green (running).
    On init failure: cyan → magenta → white (retry).
    """
    status.boot()
    time.sleep_ms(_BOOT_PAUSE_MS)
    while True:
        status.i2c_init()
        try:
            gps = gps_connect()
            display = display_connect()
        except Exception:  # noqa: BLE001
            status.init_err()
            emit({"diag": "init_err"})
            time.sleep_ms(_INIT_ERR_PAUSE_MS)
            status.boot()
            continue
        run(gps, display)


main()
