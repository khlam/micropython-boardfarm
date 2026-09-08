"""BOOT-button events across the GPIO IRQ and BOOTSEL timer backends."""

import importlib
import os
import sys

import machine
import micropython
import pytest
import rp2
import utime

_TICKS_PERIOD = 1 << 30


@pytest.mark.parametrize(
    "machine_str,backend_name",
    [
        ("RP2040 with RP2040", "bootsel"),
        ("RP2350 with RP2350", "bootsel"),
        ("Generic ESP32S3 module with ESP32S3", "esp32s3"),
        ("Some unreleased chip", "bootsel"),
    ],
    ids=["rp2040", "rp2350", "esp32s3", "unknown-chip"],
)
def test_each_chip_binds_its_documented_backend(monkeypatch, machine_str, backend_name):
    """Both RP chips share one BOOTSEL backend; anything unrecognised falls back to it."""
    button = _fresh_button(monkeypatch, machine_str)
    backend = importlib.import_module("boot_button." + backend_name)

    assert button._watch_edges is backend.watch_edges


def test_esp32s3_pulls_up_gpio0_so_the_line_never_floats(button_backend):
    """Without the pull-up, GPIO0 floats and the falling-edge IRQ fires on noise."""
    button, backend = button_backend
    if not backend.__name__.endswith("esp32s3"):
        pytest.skip("BOOTSEL backends claim no pin")

    button.on_press(lambda: None)

    pin = backend._state["button"]
    assert (pin.id, pin.mode, pin.pull) == (0, machine.Pin.IN, machine.Pin.PULL_UP)
    assert pin._irq_trigger == machine.Pin.IRQ_FALLING


def test_press_is_deferred_until_scheduler_runs(button_backend, monkeypatch):
    button, backend = button_backend
    scheduled = []
    fired = []
    monkeypatch.setattr(micropython, "schedule", lambda func, arg: scheduled.append((func, arg)))
    monkeypatch.setattr(utime, "ticks_ms", lambda: 1000)

    button.on_press(lambda: fired.append("pressed"))
    _press(backend)

    # The handler runs in interrupt/timer context, so it must only schedule.
    assert fired == []
    assert len(scheduled) == 1
    callback, arg = scheduled.pop()
    callback(arg)
    assert fired == ["pressed"]


def test_bootsel_fires_once_per_edge_not_while_the_button_is_held(button_backend, monkeypatch):
    """A held BOOTSEL must not repeat: the callback is edge-triggered, not level."""
    button, backend = button_backend
    if backend.__name__.endswith("esp32s3"):
        pytest.skip("the GPIO IRQ is edge-triggered in hardware")
    clock = [1000]
    fired = []
    monkeypatch.setattr(utime, "ticks_ms", lambda: clock[0])
    button.on_press(lambda: fired.append("pressed"))
    timer = backend._state["timer"]

    assert (timer.period, timer.mode) == (30, machine.Timer.PERIODIC)
    rp2.set_bootsel(0)
    timer.tick()
    assert fired == []

    rp2.set_bootsel(1)
    for _ in range(5):  # held down across many poll intervals
        clock[0] += 1000
        timer.tick()

    assert fired == ["pressed"]


@pytest.mark.parametrize("start_ms", [1000, _TICKS_PERIOD - 100], ids=["normal", "ticks_wrap"])
def test_bounce_is_ignored_and_next_press_accepts_debounce_boundary(
    button_backend, monkeypatch, start_ms
):
    """The ``ticks_wrap`` case pins that debouncing goes through ``utime.ticks_diff``.

    The host stub's ``ticks_diff`` is a plain subtraction, so this substitutes the
    device's wrapping arithmetic and starts the clock just below the rollover. A
    backend that inlined ``now - last_ms`` instead of calling ``ticks_diff`` would
    compute a hugely negative interval here and either wedge or fire continuously
    once the MCU has been up for ~12 days.
    """
    button, backend = button_backend
    clock = [start_ms]
    fired = []
    monkeypatch.setattr(utime, "ticks_ms", lambda: clock[0])
    monkeypatch.setattr(
        utime,
        "ticks_diff",
        lambda now, before: (
            (now - before + _TICKS_PERIOD // 2) % _TICKS_PERIOD - _TICKS_PERIOD // 2
        ),
    )
    button._state["last_ms"] = (start_ms - 150) % _TICKS_PERIOD
    button.on_press(lambda: fired.append("pressed"))

    _press(backend)
    assert fired == ["pressed"]
    clock[0] = (start_ms + 149) % _TICKS_PERIOD
    _press(backend)
    assert fired == ["pressed"]
    clock[0] = (start_ms + 150) % _TICKS_PERIOD
    _press(backend)
    assert fired == ["pressed", "pressed"]


def test_scheduled_trampoline_is_inert_before_any_registration(button_backend):
    """The trampoline can be scheduled before a callback exists; it must not raise."""
    button, _backend = button_backend

    button._run(None)

    assert button._state["callback"] is None


@pytest.fixture(
    params=[
        ("RP2040 with RP2040", "bootsel"),
        ("Generic ESP32S3 module with ESP32S3", "esp32s3"),
    ],
    ids=["bootsel", "esp32s3"],
)
def button_backend(monkeypatch, request):
    machine_str, backend_name = request.param
    button = _fresh_button(monkeypatch, machine_str)
    backend = importlib.import_module("boot_button." + backend_name)
    assert machine.pin_constructions == []
    assert machine.Timer.instances == []
    return button, backend


def _fresh_button(monkeypatch, machine_str):
    """Import ``boot_button.button`` fresh so its import-time dispatch re-runs."""
    for name in list(sys.modules):
        if name == "boot_button" or name.startswith("boot_button."):
            monkeypatch.delitem(sys.modules, name)
    monkeypatch.setattr(os, "uname", lambda: type("U", (), {"machine": machine_str}))
    return importlib.import_module("boot_button.button")


def _press(backend):
    if backend.__name__.endswith("esp32s3"):
        backend._state["button"].trigger_irq()
    else:
        rp2.set_bootsel(0)
        backend._state["timer"].tick()
        rp2.set_bootsel(1)
        backend._state["timer"].tick()
