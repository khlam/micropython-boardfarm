"""MCU-micropython firmware for the clock project.

Reads NMEA sentences from an ATGM336H GPS over UART in 10-second windows and
emits structured GPS signal data (satellites, DOP, position) as compact JSON.
Two independent 8x32 MAX7219 LED matrices (top and bottom, separate SPI buses,
shared 5 V/GND) form a 16x32 logical display with a 7-dot snake animation.
"""

import os
import random
import time
from collections import namedtuple

import ujson

from atgm336h import connect as gps_connect
from boot_status_led import status
from max7219 import connect as display_connect
from nmea import apply_parsed, build_utc_full, nmea_checksum_valid, parse_sentence

I2cBus = namedtuple("I2cBus", ("id", "sda", "scl"))
UartBus = namedtuple("UartBus", ("id", "tx", "rx"))
Device = namedtuple("Device", ("bus", "cs", "addr"))
DisplayWiring = namedtuple("DisplayWiring", ("spi_id", "sck", "mosi", "cs"))
Board = namedtuple("Board", ("name", "status_led", "i2c", "uart", "devices"))

_machine = os.uname().machine
if "ESP32S3" in _machine:
    BOARD = Board(
        name="ESP32-S3-Zero",
        status_led=21,
        i2c=I2cBus(id=0, sda=1, scl=2),
        uart=UartBus(id=1, tx=13, rx=12),
        devices={
            "gps": Device(bus="uart", cs=None, addr=None),
            "display_top": DisplayWiring(spi_id=1, sck=7, mosi=6, cs=15),
            "display_bot": DisplayWiring(spi_id=2, sck=3, mosi=4, cs=5),
        },
    )
elif "RP2350" in _machine:
    BOARD = Board(
        name="RP2350",
        status_led="LED",
        i2c=I2cBus(id=0, sda=0, scl=1),
        uart=UartBus(id=1, tx=4, rx=5),
        devices={
            "gps": Device(bus="uart", cs=None, addr=None),
            "display_top": DisplayWiring(spi_id=1, sck=10, mosi=11, cs=9),
            "display_bot": DisplayWiring(spi_id=0, sck=6, mosi=7, cs=8),
        },
    )
else:
    BOARD = Board(
        name="RP2040-Zero",
        status_led=16,
        i2c=I2cBus(id=0, sda=0, scl=1),
        uart=UartBus(id=0, tx=0, rx=1),
        devices={
            "gps": Device(bus="uart", cs=None, addr=None),
            "display_top": DisplayWiring(spi_id=1, sck=14, mosi=15, cs=8),
            "display_bot": DisplayWiring(spi_id=0, sck=6, mosi=7, cs=5),
        },
    )

WINDOW_MS = 10_000
_POLL_SLEEP_MS = 10
_BOOT_PAUSE_MS = 300
_INIT_ERR_PAUSE_MS = 1_000
_NUM_DISPLAY_MODULES = 4
_DISPLAY_W = 32
_DISPLAY_H = 16
_SNAKE_LEN = 7
_SNAKE_TICK_MS = 150


def emit(obj: dict) -> None:
    """Print one line of compact JSON to the serial port.

    All firmware output must go through this helper; raw ``print()`` calls
    elsewhere pollute the serial stream and are silently dropped by the viz
    JSON parser.
    """
    print(ujson.dumps(obj))


def _set_pixel(top_buf: bytearray, bot_buf: bytearray, n: int, x: int, y: int) -> None:
    """Light a single pixel across the top/bottom display pair.

    Two independent 8x32 panels form a 16x32 logical display.  Top panel
    (y 0-7) renders to ``top_buf``, bottom panel (y 8-15) to ``bot_buf``.
    The x-axis is mirrored (hardware quirk documented in the driver).

    Args:
        top_buf: Framebuffer for the top 8x32 display.
        bot_buf: Framebuffer for the bottom 8x32 display.
        n: Number of modules per display (4).
        x: Column (0 = left, 31 = right).
        y: Row (0 = top, 15 = bottom).
    """
    if not (0 <= x < _DISPLAY_W and 0 <= y < _DISPLAY_H):
        return
    gx = (_DISPLAY_W - 1) - x
    m = gx >> 3
    bit = 1 << (gx & 7)
    if y < 8:
        top_buf[y * n + m] |= bit
    else:
        bot_buf[(y - 8) * n + m] |= bit


def _snake_step(display_top: object, display_bot: object, snake: list) -> None:
    """Advance the snake one pixel rightward with a random vertical shift.

    Args:
        display_top: MAX7219 instance driving the top 8x32 panel.
        display_bot: MAX7219 instance driving the bottom 8x32 panel.
        snake: Mutable list of ``(x, y)`` body segments, modified in place.
    """
    hx, hy = snake[-1]
    nx = (hx + 1) % _DISPLAY_W
    ny = max(0, min(_DISPLAY_H - 1, hy + random.randint(-1, 1)))  # noqa: S311
    snake.append((nx, ny))
    snake.pop(0)

    display_top.clear_buf()
    display_bot.clear_buf()
    n = display_top.n
    for sx, sy in snake:
        _set_pixel(display_top.buf, display_bot.buf, n, sx, sy)
    display_top.refresh()
    display_bot.refresh()


def _run_window(
    gps: object, cached_date: str | None, display_top: object, display_bot: object, snake: list
) -> str | None:
    """Collect NMEA sentences for one window while animating the snake.

    Args:
        gps: An object with a ``readline() -> str | None`` method.
        cached_date: Most-recently seen GPS date (``"YYYY-MM-DD"``), or
            ``None`` if no date sentence has been received yet.
        display_top: MAX7219 instance driving the top 8x32 panel.
        display_bot: MAX7219 instance driving the bottom 8x32 panel.
        snake: Mutable list of ``(x, y)`` body segments for the animation.

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
    t_start = time.ticks_ms()
    last_snake = t_start
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
        if time.ticks_diff(now, last_snake) >= _SNAKE_TICK_MS:
            _snake_step(display_top, display_bot, snake)
            last_snake = now
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


def run(gps: object, display_top: object, display_bot: object) -> None:
    """Stream GPS data and animate the snake on the display pair.

    Args:
        gps: An object with ``readline() -> str | None`` (ATGM336H wrapper).
        display_top: MAX7219 instance driving the top 8x32 panel.
        display_bot: MAX7219 instance driving the bottom 8x32 panel.
    """
    status.streaming()
    random.seed(time.ticks_ms())
    y = _DISPLAY_H // 2
    snake = [(i, y) for i in range(_SNAKE_LEN)]
    cached_date: str | None = None
    while True:
        try:
            cached_date = _run_window(gps, cached_date, display_top, display_bot, snake)
        except Exception:  # noqa: BLE001 — a stray UART fault must not kill the loop
            status.read_err()
            emit({"diag": "read_err"})
            time.sleep_ms(_POLL_SLEEP_MS)
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
            top = BOARD.devices["display_top"]
            bot = BOARD.devices["display_bot"]
            display_top = display_connect(
                spi_id=top.spi_id,
                sck=top.sck,
                mosi=top.mosi,
                cs=top.cs,
                num_modules=_NUM_DISPLAY_MODULES,
            )
            display_bot = display_connect(
                spi_id=bot.spi_id,
                sck=bot.sck,
                mosi=bot.mosi,
                cs=bot.cs,
                num_modules=_NUM_DISPLAY_MODULES,
            )
        except Exception:  # noqa: BLE001
            status.init_err()
            emit({"diag": "init_err"})
            time.sleep_ms(_INIT_ERR_PAUSE_MS)
            status.boot()
            continue
        run(gps, display_top, display_bot)


main()
