"""Shared deterministic runtime for the matter-ld2450 firmware tests."""

import json
import os
import pathlib
import sys
from types import SimpleNamespace
from typing import ClassVar

import _matter
import machine
import neopixel
import pytest

import matter.emit as matter_emit
import matter.node as matter_node
from micropython_stubs import asyncio_extras
from micropython_stubs.testing import load_firmware_module

_FIRMWARE = pathlib.Path(__file__).parent.parent / "firmware" / "main.py"
_MODULE_NAME = "matter_ld2450_main"


class FakeTime:
    """Wrap-safe monotonic time controlled directly by each test."""

    _PERIOD = 1 << 30
    _HALF_PERIOD = 1 << 29

    def __init__(self) -> None:
        """Start at tick zero with no scripted readings."""
        self.ticks = 0
        self.script = []
        self.diff_calls = []

    def ticks_ms(self) -> int:
        """Return the next scripted tick or the current tick."""
        if self.script:
            self.ticks = self.script.pop(0)
        return self.ticks

    def ticks_diff(self, newer: int, older: int) -> int:
        """Return MicroPython's signed wrap-safe tick difference."""
        self.diff_calls.append((newer, older))
        return (newer - older + self._HALF_PERIOD) % self._PERIOD - self._HALF_PERIOD


class FakeBroadcast:
    """Record the WebSocket greeting and every emitted JSON line."""

    def __init__(self, greeting: str | None) -> None:
        """Create an empty line log."""
        self.greeting = greeting
        self.lines = []

    def send(self, line: str) -> None:
        """Record one non-blocking broadcast line."""
        self.lines.append(json.loads(line))


class FakeServer:
    """Record routes and provide scripted dashboard startup."""

    instances: ClassVar[list] = []

    def __init__(self, port: int) -> None:
        """Create a stopped server on ``port``."""
        self.port = port
        self.pages = []
        self.streams = []
        self.broadcast = None
        self.running = False
        self.start_calls = 0
        self.start_errors = []
        type(self).instances.append(self)

    def page(self, path: str, body: bytes, *, encoding: str) -> None:
        """Record one fixed-page route."""
        self.pages.append((path, body, encoding))

    def stream(self, path: str, *, greeting: str) -> FakeBroadcast:
        """Record one WebSocket route and return its broadcaster."""
        self.broadcast = FakeBroadcast(greeting)
        self.streams.append((path, self.broadcast))
        return self.broadcast

    async def start(self) -> None:
        """Raise the next scripted error or mark the server running."""
        self.start_calls += 1
        if self.start_errors:
            raise self.start_errors.pop(0)
        self.running = True


def _reset_state(*, persisted: dict | None = None, fabrics: tuple = ()) -> None:
    """Reset every process-wide fake used by the firmware module."""
    machine.reset()
    neopixel.reset()
    _matter.reset(persisted=persisted)
    _matter.seed_fabrics(list(fabrics))
    matter_node._active_node[0] = None
    matter_emit._sinks.clear()
    FakeServer.instances.clear()
    sys.modules.pop(_MODULE_NAME, None)


@pytest.fixture(autouse=True)
def reset_runtime(monkeypatch):
    """Reset process-wide MCU and Matter fakes around every test."""
    asyncio_extras.install(monkeypatch)
    _reset_state()
    yield
    _reset_state()


@pytest.fixture
def load_firmware(monkeypatch):
    """Return a loader for the complete firmware module without its infinite entry call."""

    def load(
        *,
        machine_name: str = "Generic ESP32S3 module with ESP32S3",
        persisted: dict | None = None,
        fabrics: tuple = (),
    ) -> SimpleNamespace:
        _reset_state(persisted=persisted, fabrics=fabrics)

        clock = FakeTime()
        monkeypatch.setattr(os, "uname", lambda: SimpleNamespace(machine=machine_name))
        monkeypatch.setitem(sys.modules, "time", clock)
        monkeypatch.setitem(
            sys.modules,
            "dashboard_page",
            SimpleNamespace(PAGE=b"dashboard", ENCODING="gzip"),
        )
        monkeypatch.setitem(sys.modules, "httpd", SimpleNamespace(Server=FakeServer))

        module = load_firmware_module(_FIRMWARE, _MODULE_NAME, "main")
        return SimpleNamespace(module=module, time=clock)

    return load


@pytest.fixture
def load_application(load_firmware):
    """Return a loader that also constructs the firmware application."""

    def load(**kwargs) -> SimpleNamespace:
        firmware = load_firmware(**kwargs)
        application = firmware.module._Application()
        return SimpleNamespace(
            module=firmware.module,
            application=application,
            time=firmware.time,
            server=FakeServer.instances[-1],
        )

    return load
