"""Shared deterministic runtime for the matter-radar-sensor firmware tests."""

import asyncio
import functools
import importlib
import os
import pathlib
import sys
from collections import namedtuple
from types import SimpleNamespace

import machine
import matter_native
import neopixel
import pytest
import utime
from radar_sensor_bench import Bench, project_lines, stored_attributes

import matter.node as matter_node
from micropython_stubs import asyncio_extras
from micropython_stubs.testing import StopLoopError, json_lines, load_firmware_module

_FIRMWARE = pathlib.Path(__file__).parent.parent / "firmware" / "main.py"
_MODULE_NAME = "matter_radar_sensor_main"
_ESP32S3 = "Generic ESP32S3 module with ESP32S3"
# The one fabric a commissioned boot restores: index, fabric, node, vendor, label.
_FABRIC = (1, 0x1234, 0x5678, 0xFFF1, "controller")

# What leaves the firmware during a scenario: each occupancy value ESP-Matter
# accepted for endpoint 1 with its time, the project's JSON lines, and every
# colour written to the pixel.
Outcome = namedtuple("Outcome", ("published", "lines", "pixel"))


def _reset_state(*, commissioned: bool = False, persisted: dict | None = None) -> None:
    """Reset every process-wide fake used by the firmware module."""
    machine.reset()
    neopixel.reset()
    matter_native.reset(persisted=persisted)
    matter_native.seed_fabrics([_FABRIC] if commissioned else [])
    matter_node._active_node[0] = None
    sys.modules.pop(_MODULE_NAME, None)
    for path in _FIRMWARE.parent.glob("*.py"):
        sys.modules.pop(path.stem, None)


@pytest.fixture(autouse=True)
def reset_runtime(monkeypatch):
    """Reset process-wide MCU and Matter fakes around every test."""
    asyncio_extras.install(monkeypatch)
    _reset_state()
    yield
    _reset_state()


@pytest.fixture
def run_scenario(monkeypatch, capsys):
    """Return a runner that boots the real firmware on the bench and stops it at ``until_ms``."""

    def run(
        *,
        paired: bool,
        online: bool,
        radar: str | None,
        stored_hold_light: tuple | None,
        inputs: tuple,
        until_ms: int,
    ) -> Outcome:
        _reset_state(commissioned=paired, persisted=stored_attributes(stored_hold_light))
        bench = Bench(radar=radar, online=online, inputs=inputs, until_ms=until_ms)
        clock = SimpleNamespace(ticks_ms=bench.ticks_ms, ticks_diff=bench.ticks_diff)
        real_run = asyncio.run
        monkeypatch.setitem(sys.modules, "time", clock)
        monkeypatch.setattr(utime, "ticks_ms", bench.ticks_ms)
        monkeypatch.setattr(utime, "ticks_diff", bench.ticks_diff)
        monkeypatch.setattr(asyncio, "sleep_ms", bench.sleep_ms)
        monkeypatch.setattr(
            asyncio, "run", lambda main: real_run(main, loop_factory=bench.new_loop)
        )
        monkeypatch.setattr(
            matter_native,
            "attributes_publish",
            functools.partial(bench.attributes_publish, matter_native.attributes_publish),
        )
        monkeypatch.setattr(os, "uname", lambda: SimpleNamespace(machine=_ESP32S3))
        monkeypatch.syspath_prepend(str(_FIRMWARE.parent))
        capsys.readouterr()

        module = load_firmware_module(_FIRMWARE, _MODULE_NAME, "main")
        with pytest.raises(StopLoopError):
            module.main()

        return Outcome(
            published=tuple(bench.published),
            lines=tuple(project_lines(json_lines(capsys.readouterr().out))),
            pixel=tuple(neopixel.NeoPixel.instances[0].writes),
        )

    return run


@pytest.fixture
def firmware_module(monkeypatch):
    """Return an importer for one firmware module on MicroPython's wrap-safe tick clock."""
    clock = SimpleNamespace(ticks_diff=Bench.ticks_diff)

    def load(name):
        monkeypatch.syspath_prepend(str(_FIRMWARE.parent))
        module = importlib.import_module(name)
        if hasattr(module, "time"):
            monkeypatch.setattr(module, "time", clock)
        return module

    return load


@pytest.fixture
def load_firmware(monkeypatch):
    """Return a loader that imports main.py on the named board, without its entry call."""

    def load(*, machine_name: str) -> None:
        monkeypatch.syspath_prepend(str(_FIRMWARE.parent))
        monkeypatch.setattr(os, "uname", lambda: SimpleNamespace(machine=machine_name))
        load_firmware_module(_FIRMWARE, _MODULE_NAME, "main")

    return load
