"""MCU-micropython firmware for oled-display: I²C scan, SSD1306 init, bouncing demo.

Drives an SSD1306 OLED: a "hello world!" banner bounces and reflects off the
panel edges while a counter, centered on the display, ticks up once per second.
All layout and scaling lives in the chip-agnostic oled_canvas layer, so this
file holds no hard-coded pixel coordinates. Frame telemetry is streamed as
compact JSON over USB-CDC via emit() for host-side debugging.

Set SCREEN_SIZE to ``ScreenSize.RES_128x32`` or ``ScreenSize.RES_128x64`` to match
your panel. The frame rate is derived automatically — the half-height panel
transfers half the GDDRAM data and runs at ~60 fps; the full-height panel at ~30 fps.
"""

import time

import ujson

from boot_status_led import status
from i2c_bus import hard_i2c as i2c
from oled_canvas import BouncingText, OledCanvas
from ssd1306 import OLED_ADDRS, SSD1306, ScreenSize

SCREEN_SIZE = ScreenSize.RES_128x32
WIDTH, HEIGHT = SCREEN_SIZE
MESSAGE = "KINHOLAM.COM"

_BOOT_PAUSE_MS = 50
_RETRY_PAUSE_MS = 500
_READ_ERR_PAUSE_MS = 200
_FRAME_MS = ScreenSize.frame_ms(SCREEN_SIZE)
_COUNTER_PERIOD_MS = 1000
# Cap the centered counter so a single digit doesn't fill the whole panel.
_COUNTER_MAX_SCALE = 3


def emit(obj: dict) -> None:
    """Serialize obj to compact JSON on stdout."""
    print(ujson.dumps(obj))


def find_oled(devices: list) -> int | None:
    """Return the first configured OLED address present on the bus, or None."""
    for addr in OLED_ADDRS:
        if addr in devices:
            return addr
    return None


def init_display() -> SSD1306:
    """Scan the I²C bus and initialise the SSD1306, retrying until it comes up.

    Parks at status.no_device() when no panel answers, and at
    status.init_err() when one ACKs but driver init raises.
    """
    status.i2c_init()
    while True:
        try:
            devices = i2c.scan()
            emit({"diag": "scan", "devices": devices})
            addr = find_oled(devices)
            if addr is None:
                status.no_device()
                emit({"diag": "no_device", "devices": devices})
                time.sleep_ms(_RETRY_PAUSE_MS)
                continue
            oled = SSD1306(i2c, WIDTH, HEIGHT, addr)
            emit({"diag": "oled_ok", "addr": addr})
        except OSError as err:
            status.init_err()
            emit({"diag": "init_err", "err": str(err)})
            time.sleep_ms(_RETRY_PAUSE_MS)
        else:
            return oled


def render(oled: SSD1306) -> None:
    """Render the bouncing banner plus a once-per-second centered counter forever.

    The whole frame's device I/O is wrapped so a transient I²C fault flips the
    LED to read_err, emits a diagnostic, and resumes — the loop never dies.
    """
    canvas = OledCanvas(oled, WIDTH, HEIGHT)
    banner = BouncingText(canvas, MESSAGE)
    counter = BouncingText(canvas, "0", max_scale=_COUNTER_MAX_SCALE, random_reflect=True)
    count = 0
    last_tick = time.ticks_ms()
    status.streaming()
    while True:
        try:
            now = time.ticks_ms()
            if time.ticks_diff(now, last_tick) >= _COUNTER_PERIOD_MS:
                count += 1
                last_tick = now
                counter.update_text(str(count))
                emit({"t": now, "count": count, "x": banner.x, "y": banner.y})
            canvas.clear()
            banner.step()
            banner.draw()
            counter.step()
            counter.draw()
            canvas.show()
        except OSError as err:
            status.read_err()
            emit({"diag": "read_err", "err": str(err)})
            time.sleep_ms(_READ_ERR_PAUSE_MS)
            status.streaming()
        time.sleep_ms(_FRAME_MS)


def main() -> None:
    """Run boot → init → render."""
    status.boot()
    time.sleep_ms(_BOOT_PAUSE_MS)
    oled = init_display()
    render(oled)


main()
