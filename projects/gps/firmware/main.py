"""MCU-micropython firmware for the gps project: ATGM336H NMEA collection over UART.

Reads every NMEA sentence that arrives in a 10-second window and emits them as a
single JSON object. No I²C or bus scan — UART is always available; the LED goes
straight from boot to streaming.
"""

import time

import ujson

from atgm336h import gps
from boot_status_led import status

# Duration of each collection window in milliseconds.
WINDOW_MS = 10_000

# Pacing sleep inside the collection loop — yields the MicroPython scheduler
# and bounds busy-looping between readline() calls.
_POLL_SLEEP_MS = 10

# Boot settle time before entering the stream loop.
_BOOT_PAUSE_MS = 300


def emit(obj: dict) -> None:
    """Print one line of compact JSON to the serial port.

    All firmware output must go through this helper; raw ``print()`` calls
    elsewhere pollute the serial stream and are silently dropped by the viz
    JSON parser.
    """
    print(ujson.dumps(obj))


def stream() -> None:
    """Collect NMEA sentences for WINDOW_MS, emit a batch, repeat forever.

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
    """Run boot → stream. MicroPython entry point."""
    status.boot()
    time.sleep_ms(_BOOT_PAUSE_MS)
    stream()


main()
