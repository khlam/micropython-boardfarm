"""Shared deterministic runtime for the Matter colour light firmware tests."""

import contextlib
import functools
import os
import pathlib
import sys
import types
from collections import namedtuple
from types import SimpleNamespace

import machine
import matter_native
import neopixel
import pytest
import utime
from color_light_bench import FABRIC, Bench, stored_attributes

import matter.node as matter_node
from micropython_stubs.testing import StopLoopError, json_lines

_FIRMWARE = pathlib.Path(__file__).parent.parent / "firmware"
_MAIN = _FIRMWARE / "main.py"
_MAIN_MODULE = "matter_project_main"
_ESP32S3 = "Generic ESP32S3 module with ESP32S3"

# What leaves the firmware during a run: the JSON lines, every colour written
# to the pixel, and each attribute batch ESP-Matter accepted, by name.
Outcome = namedtuple("Outcome", ("lines", "pixel", "published"))


def _reset_state(*, paired: bool = False, persisted: dict | None = None) -> None:
    """Reset every process-wide fake used by the firmware."""
    machine.reset()
    neopixel.reset()
    matter_native.reset(persisted=persisted)
    matter_native.seed_fabrics([FABRIC] if paired else [])
    matter_node._active_node[0] = None
    for name in (_MAIN_MODULE, "color", "color.convert"):
        sys.modules.pop(name, None)


@pytest.fixture(autouse=True)
def reset_runtime():
    """Reset process-wide MCU and Matter fakes around every test."""
    _reset_state()
    yield
    _reset_state()


@pytest.fixture
def color_module(monkeypatch):
    """Import a fresh copy of the project's public color module."""
    monkeypatch.syspath_prepend(str(_FIRMWARE))
    module = __import__("color")
    yield module
    sys.modules.pop("color.convert", None)
    sys.modules.pop("color", None)


@pytest.fixture
def run_light(monkeypatch, capsys):
    """Return a runner that boots the whole firmware on the bench and stops it at ``until_ms``.

    After the loop stops, as after Ctrl-C, each colour in ``typed`` goes to the
    firmware's ``set_color()`` at the REPL.
    """

    def run(
        *,
        paired: bool,
        online: bool,
        stored_light: tuple | None,
        inputs: tuple,
        until_ms: int,
        typed: tuple = (),
        machine_name: str = _ESP32S3,
    ) -> Outcome:
        _reset_state(paired=paired, persisted=stored_attributes(stored_light))
        bench = Bench(online=online, inputs=inputs, until_ms=until_ms)
        # On the board, time is utime.
        monkeypatch.setitem(sys.modules, "time", utime)
        monkeypatch.setattr(utime, "ticks_ms", bench.ticks_ms)
        monkeypatch.setattr(utime, "sleep_ms", bench.sleep_ms)
        monkeypatch.setattr(
            matter_native, "start", functools.partial(bench.start, matter_native.start)
        )
        monkeypatch.setattr(
            matter_native,
            "attributes_publish",
            functools.partial(bench.attributes_publish, matter_native.attributes_publish),
        )
        monkeypatch.setattr(os, "uname", lambda: SimpleNamespace(machine=machine_name))
        monkeypatch.syspath_prepend(str(_FIRMWARE))
        capsys.readouterr()

        module = _run_main()
        for color in typed:
            module.set_color(color)

        return Outcome(
            lines=tuple(json_lines(capsys.readouterr().out)),
            pixel=tuple(neopixel.NeoPixel.instances[0].writes),
            published=tuple(bench.published),
        )

    return run


def _run_main() -> types.ModuleType:
    """Run main.py from its first line to its last, until the bench stops its loop.

    Returns:
        The firmware module, holding what main.py leaves in scope for the REPL.
    """
    module = types.ModuleType(_MAIN_MODULE)
    module.__file__ = str(_MAIN)
    sys.modules[_MAIN_MODULE] = module
    code = compile(_MAIN.read_text(), str(_MAIN), "exec")
    with contextlib.suppress(StopLoopError):
        exec(code, module.__dict__)
    return module
