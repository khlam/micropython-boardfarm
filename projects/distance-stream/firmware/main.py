"""MCU-micropython firmware for distance-stream: I²C scan, VL53L0X init, JSON stream."""

import time
from collections import namedtuple

import ujson

from boot_status_led import status
from i2c_bus import soft_i2c as i2c
from vl53l0x import VL53L0X

TOF_ADDRESS = 0x29

# Sensor reports ~8190 mm (and up to 65535) when nothing is in range;
# emit null so the viz shows a gap instead of a spurious large value.
OUT_OF_RANGE_MM = 8190

# Median-of-5 rejects single-sample glitches; EMA τ≈200 ms smooths residual noise.
# Both reset on out-of-range to avoid bridging across gaps.
MEDIAN_N = 5
EMA_ALPHA = 0.1

# 20 ms budget → ~50 Hz; EMA compensates for the higher per-sample noise vs 40 ms.
TIMING_BUDGET_US = 20_000

_BOOT_PAUSE_MS = 50
_RETRY_PAUSE_MS = 500
_READ_ERR_PAUSE_MS = 200
_SOFT_RESET_PAUSE_MS = 2
_SOFT_RESET_POLLS = 50

_REG_SOFT_RESET = 0xBF
_REG_MODEL_ID = 0xC0
_MODEL_ID_BOOTED = 0xEE

FilterResult = namedtuple("FilterResult", ("smoothed_mm", "median_buf", "ema"))


def emit(obj: dict) -> None:
    """Serialize obj to compact JSON on stdout."""
    print(ujson.dumps(obj))


def soft_reset_sensor(bus: object, address: int = TOF_ADDRESS) -> bool:
    """Soft-reset the VL53L0X and poll until it reboots.

    Clears any half-init state from a previous attempt before the
    driver touches calibration registers.

    Args:
        bus: Object exposing writeto_mem / readfrom_mem.
        address: 7-bit I²C address of the sensor.

    Returns:
        True if the chip signals ready within the poll budget, False otherwise.
    """
    try:
        bus.writeto_mem(address, _REG_SOFT_RESET, b"\x00")
        time.sleep_ms(_SOFT_RESET_PAUSE_MS)
        bus.writeto_mem(address, _REG_SOFT_RESET, b"\x01")
        time.sleep_ms(_SOFT_RESET_PAUSE_MS)
        for _ in range(_SOFT_RESET_POLLS):
            if bus.readfrom_mem(address, _REG_MODEL_ID, 1)[0] == _MODEL_ID_BOOTED:
                return True
            time.sleep_ms(_SOFT_RESET_PAUSE_MS)
    except OSError:
        return False
    return False


def init_sensor() -> VL53L0X:
    """Scan i2c bus and initialise VL53L0X, retrying until it comes up.

    Parks at status.no_device() when no device is present at 0x29, and at
    status.init_err() when the device ACKs but driver init raises.
    """
    status.i2c_init()
    while True:
        try:
            devices = i2c.scan()
            emit({"diag": "scan", "devices": devices})
            if TOF_ADDRESS not in devices:
                status.no_device()
                emit({"diag": "no_device", "devices": devices})
                time.sleep_ms(_RETRY_PAUSE_MS)
                continue
            # This breakout variant signals ranging done via bit 6 of
            # _RESULT_INTERRUPT_STATUS and hangs in the SPAD-info procedure;
            # both quirks apply on all MCUs, not just ESP32 or RP.
            soft_reset_sensor(i2c)
            tof = VL53L0X(i2c, skip_spad_info=True, interrupt_status_mask=0xFF)
            tof.set_measurement_timing_budget(TIMING_BUDGET_US)
            tof.start()
            emit({"diag": "tof_ok", "addr": tof.address})
        except (OSError, RuntimeError) as err:
            # OSError = I²C NACK; RuntimeError = driver poll timeout.
            status.init_err()
            emit({"diag": "init_err", "err": str(err)})
            time.sleep_ms(_RETRY_PAUSE_MS)
        else:
            return tof


def _filter_step(distance_mm: int, median_buf: list[int], ema: float | None) -> FilterResult:
    """Median + EMA smoothing for one in-range sample.

    Raw VL53L0X readings can have occasional in-range spikes
    that slip past the out-of-range gate and a few mm of jitter on a
    stationary target. The median-of-MEDIAN_N drops the spikes; EMA
    smooths the residual jitter. Caller must gate out-of-range first;
    median_buf is mutated in place.

    Args:
        distance_mm: An in-range reading in mm.
        median_buf: Rolling window of recent in-range samples.
        ema: Previous EMA, or None on the first call.

    Returns:
        FilterResult(smoothed_mm, median_buf, ema).
    """
    median_buf.append(distance_mm)
    if len(median_buf) > MEDIAN_N:
        median_buf.pop(0)
    median = sorted(median_buf)[len(median_buf) // 2]
    ema = median if ema is None else ema * (1 - EMA_ALPHA) + median * EMA_ALPHA
    return FilterResult(int(ema + 0.5), median_buf, ema)


def stream(tof: VL53L0X) -> None:
    """Stream filtered distance samples indefinitely.

    read() blocks until the next sample is ready, so the loop is
    self-paced at the configured timing budget with no extra sleep.
    """
    median_buf: list[int] = []
    ema: float | None = None
    status.streaming()
    while True:
        try:
            distance_mm = tof.read()
            if distance_mm >= OUT_OF_RANGE_MM:
                del median_buf[:]
                ema = None
                emit({"t": time.ticks_ms(), "distance_mm": None})
            else:
                result = _filter_step(distance_mm, median_buf, ema)
                median_buf, ema = result.median_buf, result.ema
                emit({"t": time.ticks_ms(), "distance_mm": result.smoothed_mm})
        except (OSError, RuntimeError) as err:
            # Transient fault; restart continuous mode before resuming.
            status.read_err()
            emit({"diag": "read_err", "err": str(err)})
            try:
                tof.stop()
                tof.start()
            except (OSError, RuntimeError):
                pass
            del median_buf[:]
            ema = None
            time.sleep_ms(_READ_ERR_PAUSE_MS)
            status.streaming()


def main() -> None:
    """Run boot → init → stream."""
    status.boot()
    time.sleep_ms(_BOOT_PAUSE_MS)
    tof = init_sensor()
    stream(tof)


main()
