"""Shared fakes and AST-loading helpers for firmware main.py tests."""

from __future__ import annotations

import ast
import asyncio
import io
import json
import pathlib
import types
from contextlib import redirect_stdout
from typing import Any, ClassVar

import pytest
import ujson

# (os.uname().machine string, expected BOARD.name) — exercises every per-chip
# branch of a project main.py's BOARD table on a real import.
BOARD_CHIPS = [
    ("RP2040 with RP2040", "RP2040-Zero"),
    ("RP2350 with RP2350", "RP2350"),
    ("Generic ESP32S3 module with ESP32S3", "ESP32-S3-Zero"),
]


class DeviceNotFoundError(Exception):
    """Stand-in for a driver's DeviceNotFoundError in full-import tests.

    The happy path never raises it; it only needs to exist so the driver stub
    can expose it under the name main.py imports.
    """


class FakeTime:
    """Monotonic ticks_ms counter, ticks_diff, and no-op sleep_ms."""

    def __init__(self) -> None:
        """Initialise the monotonic counter at zero."""
        self.ticks = 0

    def ticks_ms(self) -> int:
        """Advance and return the monotonic tick counter."""
        self.ticks += 1
        return self.ticks

    def ticks_diff(self, a: int, b: int) -> int:
        """Return the difference between two tick values."""
        return a - b

    def sleep_ms(self, _ms: int) -> None:
        """No-op sleep for test determinism."""


class FakeStatus:
    """Record every transition call by name into self.calls."""

    def __init__(self) -> None:
        """Initialise an empty transition call log."""
        self.calls: list[str] = []

    def __getattr__(self, name: str) -> Any:
        """Return a recorder closure for any non-private attribute."""
        if name.startswith("_"):
            raise AttributeError(name)

        def _rec() -> None:
            self.calls.append(name)

        return _rec


def load_firmware_code(firmware_path: pathlib.Path, keep_funcs: set[str]) -> types.CodeType:
    """AST-load a firmware main.py, keeping only assignments and named functions.

    Args:
        firmware_path: Path to the firmware main.py file.
        keep_funcs: Function names to retain from the module body.

    Returns:
        Compiled code object ready for ``exec()`` into a namespace dict.
    """
    src = firmware_path.read_text()
    tree = ast.parse(src)
    kept: list[ast.stmt] = [
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        or (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in keep_funcs)
    ]
    module = ast.Module(body=kept, type_ignores=[])
    ast.fix_missing_locations(module)
    return compile(module, str(firmware_path), "exec")


def firmware_namespace(
    firmware_path: pathlib.Path,
    keep_funcs: set[str],
    **namespace: Any,
) -> types.SimpleNamespace:
    """Exec AST-filtered firmware into a namespace with standard fakes.

    Args:
        firmware_path: Path to the firmware main.py file.
        keep_funcs: Function names to retain from the module body.
        **namespace: Project-specific globals required by the retained code.

    Returns:
        SimpleNamespace with ``ns``, ``time``, and ``status`` attributes.
    """
    fake_time = FakeTime()
    fake_status = FakeStatus()
    ns = {"time": fake_time, "status": fake_status, "ujson": ujson, **namespace}
    exec(load_firmware_code(firmware_path, keep_funcs), ns)  # noqa: S102
    return types.SimpleNamespace(ns=ns, time=fake_time, status=fake_status)


def build_full_import_stubs(
    driver_key: str,
    driver_stub: types.SimpleNamespace,
    status_stub: FakeStatus,
) -> dict[str, Any]:
    """Build the sys.modules stub map for a project's full-import test.

    Every project's main.py imports the same base set (time, ujson,
    boot_status_led) plus its one driver; only the driver name and stub differ.

    Args:
        driver_key: Top-level module name main.py imports the driver from.
        driver_stub: Namespace exposing the driver class and DeviceNotFoundError.
        status_stub: FakeStatus recording LED transitions.

    Returns:
        Mapping of module name to stub, ready for monkeypatch.setitem.
    """
    return {
        "time": FakeTime(),
        "ujson": json,
        "boot_status_led": types.SimpleNamespace(status=status_stub),
        "boot_status_led.status": status_stub,
        driver_key: driver_stub,
    }


class ScriptedFake:
    """Base for init-test driver fakes that pop a `script` on each construction.

    Subclasses declare their own ``script: ClassVar[list]`` and assign their
    distinguishing attributes after calling ``super().__init__()``. The base
    reads ``type(self).script`` (never ``self.script``) so each subclass keeps
    its own list rather than sharing this base's mutable default.
    """

    script: ClassVar[list] = []

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        """Pop the next scripted outcome and raise it when it is an exception."""
        if type(self).script:
            outcome = type(self).script.pop(0)
            if isinstance(outcome, Exception):
                raise outcome


class StopLoopError(Exception):
    """Sentinel a scripted fake raises to break stream()'s otherwise-infinite loop."""


def run_stream(main_ns: types.SimpleNamespace, sensor: Any) -> list[dict]:
    """Drive stream(sensor) until the fake raises StopLoopError; return JSON lines.

    Args:
        main_ns: Namespace from firmware_namespace, exposing ``ns["stream"]``.
        sensor: Scripted fake passed straight to stream().

    Returns:
        One parsed dict per non-blank JSON line emitted to stdout.
    """
    stream = main_ns.ns["stream"]
    buf = io.StringIO()
    with redirect_stdout(buf), pytest.raises(StopLoopError):
        stream(sensor)
    return [json.loads(line) for line in buf.getvalue().splitlines() if line.strip()]


def run_async_stream(main_ns: types.SimpleNamespace, sensor: Any) -> list[dict]:
    """Drive an `async def stream(sensor)` until the fake raises StopLoopError.

    Args:
        main_ns: Namespace from firmware_namespace, exposing ``ns["stream"]``.
        sensor: Scripted fake passed straight to stream().

    Returns:
        One parsed dict per non-blank JSON line emitted to stdout.
    """
    stream = main_ns.ns["stream"]
    buf = io.StringIO()
    with redirect_stdout(buf), pytest.raises(StopLoopError):
        asyncio.run(stream(sensor))
    return [json.loads(line) for line in buf.getvalue().splitlines() if line.strip()]


def samples(lines: list[dict]) -> list[dict]:
    """Return the data lines — those without a "diag" key."""
    return [ln for ln in lines if "diag" not in ln]


def diags(lines: list[dict]) -> list:
    """Return the "diag" values from the diagnostic lines."""
    return [ln["diag"] for ln in lines if "diag" in ln]
