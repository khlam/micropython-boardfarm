"""MCU-micropython firmware for the gps project: ATGM336H NMEA collection over UART.

Reads every NMEA sentence that arrives in a 10-second window and emits them as a
single JSON object.

LED colour map (boot_status_led):
    white   - firmware alive, atgm336h package import about to run
    orange  - atgm336h package missing from firmware (recompile needed)
    cyan    - package imported, UART open in progress
    magenta - UART open failed (wiring / pin issue)
    green   - streaming normally
    red     - transient readline() fault; recovers automatically
"""

import time

import ujson

from boot_status_led import status

# Firmware is alive — light LED immediately before any hardware init.
status.boot()

# If the atgm336h package is not in the firmware, show orange and halt.
# Orange here means: rebuild with `docker compose up --build pi-compile`.
try:
    from atgm336h import connect as _connect_gps
except Exception:  # noqa: BLE001
    status.no_device()
    while True:
        time.sleep_ms(500)

# Duration of each collection window in milliseconds.
WINDOW_MS = 10_000

# Pacing sleep inside the collection loop — yields the MicroPython scheduler
# and bounds busy-looping between readline() calls.
_POLL_SLEEP_MS = 10

# Boot settle time before opening the UART.
_BOOT_PAUSE_MS = 300

# Retry pause when the UART cannot be opened.
_INIT_ERR_PAUSE_MS = 1_000

# Best-effort TX buffer check: poll sys.stdout before each print() so a full
# USB-CDC ring buffer never stalls the collection loop.  uselect is a
# MicroPython built-in absent on CPython; NameError covers the case where the
# test conftest strips the import statements from the AST before exec().
try:
    import sys as _sys

    import uselect as _uselect

    _poll = _uselect.poll()
    _poll.register(_sys.stdout, _uselect.POLLOUT)
    _USELECT_OK = True
except (ImportError, AttributeError, NameError):
    _USELECT_OK = False
    _poll = None


def emit(obj: dict) -> None:
    """Print one line of compact JSON to the serial port.

    Checks that the USB-CDC transmit buffer has space before writing;
    silently drops the line if the host is not consuming output so the
    collection loop is never stalled. All firmware output must go through
    this helper; raw ``print()`` calls elsewhere pollute the serial stream
    and are silently dropped by the viz JSON parser.

    Args:
        obj: Serialisable dict to emit as a single JSON line.
    """
    if _USELECT_OK and not _poll.poll(0):
        return
    print(ujson.dumps(obj))


def stream(gps: object) -> None:
    """Collect NMEA sentences for WINDOW_MS, emit a batch, repeat forever.

    Args:
        gps: An object with a ``readline() -> str | None`` method.

    Each successful window emits::

        {"t": <ms>, "window_ms": 10000, "sentences": [...], "count": <n>}

    An empty window (no GPS data) emits::

        {"diag": "no_data", "t": <ms>}

    A UART exception emits a ``read_err`` diagnostic, resets the LED to
    streaming, and starts a fresh window immediately.
    """
    status.streaming()
    while True:
        sentences: list[str] = []
        t_start = time.ticks_ms()
        try:
            while time.ticks_diff(time.ticks_ms(), t_start) < WINDOW_MS:
                line = gps.readline()
                if line is not None:
                    sentences.append(line)
                time.sleep_ms(_POLL_SLEEP_MS)
        except Exception as err:  # noqa: BLE001
            status.read_err()
            emit({"diag": "read_err", "err": str(err)})
            status.streaming()
            continue
        if sentences:
            emit(
                {
                    "t": time.ticks_ms(),
                    "window_ms": WINDOW_MS,
                    "sentences": sentences,
                    "count": len(sentences),
                }
            )
        else:
            emit({"diag": "no_data", "t": time.ticks_ms()})


def main() -> None:
    """Run boot → UART init → stream. MicroPython entry point.

    LED sequence: white → cyan (UART opening) → green (streaming).
    On UART failure: cyan → magenta → white (retry).
    """
    time.sleep_ms(_BOOT_PAUSE_MS)
    while True:
        status.i2c_init()  # cyan: attempting UART open
        try:
            gps = _connect_gps()
        except Exception as err:  # noqa: BLE001
            status.init_err()  # magenta: UART open failed
            emit({"diag": "init_err", "err": str(err)})
            time.sleep_ms(_INIT_ERR_PAUSE_MS)
            status.boot()  # white: retrying
            continue
        stream(gps)


main()
