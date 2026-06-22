"""Shared fakes and AST-loading helpers for firmware main.py tests."""

from __future__ import annotations

import ast
import pathlib
import types
from typing import Any

import ujson


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
        or (isinstance(node, ast.FunctionDef) and node.name in keep_funcs)
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
