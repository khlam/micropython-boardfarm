"""Host CPython tests for the event-driven BOOT button.

Each chip backend is dispatched on os.uname().machine and turns a hardware edge
(GPIO0 IRQ or a BOOTSEL poll) into a single debounced, deferred callback.
"""

import importlib
import os
import sys

import micropython
import rp2

from micropython_stubs.testing import BOARD_CHIPS


def _import_button(monkeypatch, machine_str):
    """Re-import boot_button.button under a simulated chip; return the module."""
    for mod in list(sys.modules):
        if mod.startswith("boot_button"):
            del sys.modules[mod]
    monkeypatch.setattr(os, "uname", lambda: type("U", (), {"machine": machine_str}))
    return importlib.import_module("boot_button.button")


def test_dispatch_picks_correct_backend(monkeypatch):
    expected = {
        "RP2040 with RP2040": "boot_button.rp2040",
        "RP2350 with RP2350": "boot_button.rp2350",
        "Generic ESP32S3 module with ESP32S3": "boot_button.esp32s3",
    }
    for machine_str, _board in BOARD_CHIPS:
        button = _import_button(monkeypatch, machine_str)
        assert button._on_press.__module__ == expected[machine_str]


def test_esp32s3_irq_fires_callback(monkeypatch):
    button = _import_button(monkeypatch, "Generic ESP32S3 module with ESP32S3")
    esp32s3 = importlib.import_module("boot_button.esp32s3")
    fired = []

    button.on_press(lambda: fired.append(1))
    # GPIO0 is configured as a pulled-up input with a falling-edge IRQ.
    assert esp32s3._state["button"].mode == "IN"
    assert esp32s3._state["button"]._irq_trigger == "IRQ_FALLING"

    esp32s3._state["button"].trigger_irq()
    assert fired == [1]


def test_esp32s3_debounces_rapid_presses(monkeypatch):
    button = _import_button(monkeypatch, "Generic ESP32S3 module with ESP32S3")
    esp32s3 = importlib.import_module("boot_button.esp32s3")
    fired = []

    # Hold the debounce clock still so two edges land in the same window.
    monkeypatch.setattr(esp32s3.utime, "ticks_ms", lambda: 1000)
    button.on_press(lambda: fired.append(1))

    esp32s3._state["button"].trigger_irq()
    esp32s3._state["button"].trigger_irq()
    assert fired == [1]


def _rp_backend(monkeypatch, machine_str, backend_name):
    """Import an RP backend via dispatch and return (button, backend) modules."""
    button = _import_button(monkeypatch, machine_str)
    return button, importlib.import_module(backend_name)


def test_rp2040_fires_on_press_edge(monkeypatch):
    button, rp2040 = _rp_backend(monkeypatch, "RP2040 with RP2040", "boot_button.rp2040")
    fired = []
    # Controllable debounce clock so the second press lands outside the window.
    clock = [1000]
    monkeypatch.setattr(rp2040.utime, "ticks_ms", lambda: clock[0])
    button.on_press(lambda: fired.append(1))

    # Idle poll: nothing pressed, no callback.
    rp2040._state["timer"].tick()
    assert fired == []

    # Press edge fires once; holding it down does not re-fire.
    rp2.set_bootsel(1)
    rp2040._state["timer"].tick()
    rp2040._state["timer"].tick()
    assert fired == [1]

    # Release then press again (past the debounce window) fires a second time.
    rp2.set_bootsel(0)
    rp2040._state["timer"].tick()
    clock[0] += 1000
    rp2.set_bootsel(1)
    rp2040._state["timer"].tick()
    assert fired == [1, 1]


def test_rp2350_fires_on_press_edge(monkeypatch):
    button, rp2350 = _rp_backend(monkeypatch, "RP2350 with RP2350", "boot_button.rp2350")
    fired = []
    button.on_press(lambda: fired.append(1))

    rp2.set_bootsel(1)
    rp2350._state["timer"].tick()
    rp2350._state["timer"].tick()
    assert fired == [1]


def test_press_defers_through_micropython_schedule(monkeypatch):
    """The handler must hand the callback to micropython.schedule, not call it inline."""
    button = _import_button(monkeypatch, "RP2040 with RP2040")
    rp2040 = importlib.import_module("boot_button.rp2040")
    scheduled = []

    def _record(func, arg):
        scheduled.append((func, arg))

    monkeypatch.setattr(micropython, "schedule", _record)
    fired = []
    button.on_press(lambda: fired.append(1))

    rp2.set_bootsel(1)
    rp2040._state["timer"].tick()
    # Callback was deferred, not run inside the timer handler.
    assert fired == []
    assert len(scheduled) == 1
    func, arg = scheduled[0]
    func(arg)
    assert fired == [1]
