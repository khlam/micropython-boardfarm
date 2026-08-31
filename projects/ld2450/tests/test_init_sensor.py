"""Host CPython pytest tests for init_sensor() in ld2450 firmware.

The driver opens its own UART and waits for a valid report, so init_sensor()
takes no arguments and constructs driver(Model.LD2450, bus_id=, tx=, rx=) from
BOARD, then awaits wait_ready(). Covers: happy path, no_device retry (DeviceNotFoundError
from wait_ready()), and init error retry (OSError from wait_ready()).
"""

import asyncio
import os
import pathlib
from collections import namedtuple
from typing import ClassVar

from micropython_stubs.testing import firmware_namespace
from radar import DeviceNotFoundError, Model

_FIRMWARE = pathlib.Path(__file__).parent.parent / "firmware" / "main.py"
_KEEP_FUNCS = {"emit", "init_sensor"}
Board = namedtuple("Board", ("name", "uart_id", "tx", "rx"))
_TEST_BOARD = Board(name="RP2040-Zero", uart_id=1, tx=4, rx=5)


class _FakeLD2450:
    """Stands in for radar.driver(): records what was selected and opened.

    Unlike a ScriptedFake, the fault fires from wait_ready() rather than
    __init__ — matching the real driver, whose constructor never raises.
    """

    script: ClassVar[list] = []

    def __init__(self, model, *, bus_id, tx, rx) -> None:
        self.model = model
        self.bus_id = bus_id
        self.tx = tx
        self.rx = rx

    async def wait_ready(self) -> None:
        if _FakeLD2450.script:
            outcome = _FakeLD2450.script.pop(0)
            if isinstance(outcome, Exception):
                raise outcome


def _make_init_ns():
    """Create AST-loaded namespace with _FakeLD2450 injected."""
    _FakeLD2450.script = []
    return firmware_namespace(
        _FIRMWARE,
        _KEEP_FUNCS,
        os=os,
        namedtuple=namedtuple,
        asyncio=asyncio,
        BOARD=_TEST_BOARD,
        driver=_FakeLD2450,
        Model=Model,
        DeviceNotFoundError=DeviceNotFoundError,
    )


def test_init_sensor_happy_path():
    init_ns = _make_init_ns()
    radar = asyncio.run(init_ns.ns["init_sensor"]())
    assert isinstance(radar, _FakeLD2450)
    assert radar.model == Model.LD2450
    assert radar.bus_id == _TEST_BOARD.uart_id
    assert radar.tx == _TEST_BOARD.tx
    assert radar.rx == _TEST_BOARD.rx
    assert init_ns.status.calls == ["uart_init"]


def test_init_sensor_retries_when_device_missing():
    init_ns = _make_init_ns()
    _FakeLD2450.script = [DeviceNotFoundError("no device")]
    asyncio.run(init_ns.ns["init_sensor"]())
    assert init_ns.status.calls == ["uart_init", "no_device"]


def test_init_sensor_retries_on_oserror():
    init_ns = _make_init_ns()
    _FakeLD2450.script = [OSError("bus fault")]
    asyncio.run(init_ns.ns["init_sensor"]())
    assert init_ns.status.calls == ["uart_init", "init_err"]
