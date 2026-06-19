"""MCU-micropython firmware for the clock project.

Reads NMEA sentences from an ATGM336H GPS over UART in 10-second windows,
emits structured GPS signal data (satellites, DOP, position) as compact JSON,
and displays ``kinholam.com`` on an 8x32 MAX7219 LED matrix at the lowest
brightness.
"""

import os
import time
from collections import namedtuple

import ujson

from atgm336h import connect as gps_connect
from boot_status_led import status
from max7219 import connect as display_connect
from nmea import apply_parsed, build_utc_full, nmea_checksum_valid, parse_sentence

SpiBus = namedtuple("SpiBus", ("id", "sck", "mosi", "miso"))
I2cBus = namedtuple("I2cBus", ("id", "sda", "scl"))
UartBus = namedtuple("UartBus", ("id", "tx", "rx"))
Device = namedtuple("Device", ("bus", "cs", "addr"))
Board = namedtuple("Board", ("name", "status_led", "spi", "i2c", "uart", "devices"))

_machine = os.uname().machine
if "ESP32S3" in _machine:
    BOARD = Board(
        name="ESP32-S3-Zero",
        status_led=21,
        spi=SpiBus(id=1, sck=7, mosi=6, miso=None),
        i2c=I2cBus(id=0, sda=1, scl=2),
        uart=UartBus(id=1, tx=13, rx=12),
        devices={
            "gps": Device(bus="uart", cs=None, addr=None),
            "display": Device(bus="spi", cs=15, addr=None),
        },
    )
elif "RP2350" in _machine:
    BOARD = Board(
        name="RP2350",
        status_led="LED",
        spi=SpiBus(id=1, sck=10, mosi=11, miso=None),
        i2c=I2cBus(id=0, sda=0, scl=1),
        uart=UartBus(id=1, tx=4, rx=5),
        devices={
            "gps": Device(bus="uart", cs=None, addr=None),
            "display": Device(bus="spi", cs=9, addr=None),
        },
    )
else:
    BOARD = Board(
        name="RP2040-Zero",
        status_led=16,
        spi=SpiBus(id=1, sck=14, mosi=15, miso=None),
        i2c=I2cBus(id=0, sda=0, scl=1),
        uart=UartBus(id=0, tx=0, rx=1),
        devices={
            "gps": Device(bus="uart", cs=None, addr=None),
            "display": Device(bus="spi", cs=8, addr=None),
        },
    )

WINDOW_MS = 10_000
_POLL_SLEEP_MS = 10
_WIGGLE_MS = 120
_BOOT_PAUSE_MS = 300
_INIT_ERR_PAUSE_MS = 1_000
_DISPLAY_TEXT = "kinholam.com"


def emit(obj: dict) -> None:
    """Print one line of compact JSON to the serial port.

    All firmware output must go through this helper; raw ``print()`` calls
    elsewhere pollute the serial stream and are silently dropped by the viz
    JSON parser.
    """
    print(ujson.dumps(obj))


def _run_window(gps: object, display: object, cached_date: str | None) -> str | None:
    """Collect NMEA sentences for one window and emit a GPS signal result.

    Args:
        gps: An object with a ``readline() -> str | None`` method.
        display: A MAX7219 instance; its wiggle is advanced during the window.
        cached_date: Most-recently seen GPS date (``"YYYY-MM-DD"``), or
            ``None`` if no date sentence has been received yet.

    Returns:
        Updated ``cached_date``; unchanged if no new date was seen this window.
    """
    signals: dict = {}
    in_use_set: set = set()
    total_in_view: dict = {}
    dop: dict = {}
    position: dict = {}
    utc_time: str | None = None
    saw_data = False
    wiggle_tick = time.ticks_ms()
    t_start = time.ticks_ms()
    while time.ticks_diff(time.ticks_ms(), t_start) < WINDOW_MS:
        line = gps.readline()
        if line is not None and nmea_checksum_valid(line):
            saw_data = True
            new_signals, new_in_use, new_total, new_dop, new_pos, new_parsed = parse_sentence(line)
            signals.update(new_signals)
            in_use_set |= new_in_use
            total_in_view.update(new_total)
            dop.update(new_dop)
            position.update(new_pos)
            utc_time, cached_date = apply_parsed(new_parsed, utc_time, cached_date)
        now = time.ticks_ms()
        if time.ticks_diff(now, wiggle_tick) >= _WIGGLE_MS:
            display.wiggle_step()
            wiggle_tick = now
        time.sleep_ms(_POLL_SLEEP_MS)
    if saw_data:
        emit(
            {
                "window_ms": WINDOW_MS,
                "utc": build_utc_full(utc_time, cached_date),
                "sats_in_use": len(in_use_set),
                "sats_in_view": sum(total_in_view.values()),
                "hdop": dop.get("hdop"),
                "vdop": dop.get("vdop"),
                "pdop": dop.get("pdop"),
                "lat": position.get("lat"),
                "lon": position.get("lon"),
                "signals": list(signals.values()),
            }
        )
    else:
        emit({"diag": "no_data"})
    return cached_date


def run(gps: object, display: object) -> None:
    """Show ``kinholam.com`` on the matrix and stream GPS signal data forever.

    Args:
        gps: An object with ``readline() -> str | None`` (ATGM336H wrapper).
        display: A MAX7219 instance.
    """
    display.set_intensity(0)
    display.show_auto(_DISPLAY_TEXT)
    status.streaming()
    cached_date: str | None = None
    while True:
        try:
            cached_date = _run_window(gps, display, cached_date)
        except Exception:  # noqa: BLE001 — a stray UART fault must not kill the loop
            status.read_err()
            emit({"diag": "read_err"})
            status.streaming()


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
            gps = gps_connect(uart_id=BOARD.uart.id, tx=BOARD.uart.tx, rx=BOARD.uart.rx)
            display = display_connect(
                spi_id=BOARD.spi.id,
                sck=BOARD.spi.sck,
                mosi=BOARD.spi.mosi,
                cs=BOARD.devices["display"].cs,
            )
        except Exception:  # noqa: BLE001
            status.init_err()
            emit({"diag": "init_err"})
            time.sleep_ms(_INIT_ERR_PAUSE_MS)
            status.boot()
            continue
        run(gps, display)


main()
