"""Host CPython pytest bootstrap for the oled-display firmware.

Exposes the `main_ns` fixture: an AST-loaded namespace containing main.py's
constants, emit(), find_oled(), init_display(), and render(), with fakes for
the `time` and `status` side effects and the real OledCanvas/BouncingText
classes — so render() is exercisable in tests without the module's top-level
main() call running (which would otherwise block forever in the render loop).
"""

import ast
import pathlib
from types import SimpleNamespace

import pytest

_HERE = pathlib.Path(__file__).parent.resolve()
_FIRMWARE = _HERE.parent / "firmware" / "main.py"
_KEEP_FUNCS = {"emit", "find_oled", "init_display", "render"}


class _FakeTime:
    """Deterministic stand-in for `time`: ticks advance only via sleep_ms."""

    def __init__(self) -> None:
        self.now = 0

    def ticks_ms(self) -> int:
        return self.now

    def ticks_diff(self, a: int, b: int) -> int:
        return a - b

    def sleep_ms(self, ms: int) -> None:
        self.now += ms


class _FakeStatus:
    """Records LED-state transitions in call order for assertions."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def boot(self) -> None:
        self.calls.append("boot")

    def i2c_init(self) -> None:
        self.calls.append("i2c_init")

    def no_device(self) -> None:
        self.calls.append("no_device")

    def init_err(self) -> None:
        self.calls.append("init_err")

    def streaming(self) -> None:
        self.calls.append("streaming")

    def read_err(self) -> None:
        self.calls.append("read_err")


def _load_main_namespace(fake_time, fake_status):
    """Parse main.py and exec the constants + key functions in a fresh namespace.

    Keeps only module-level Assign nodes (constants) and the FunctionDefs the
    tests need. Drops Import nodes (the caller seeds substitutes for `time`,
    `status`, `ujson`, and the oled_canvas classes) and the trailing Expr that
    calls main() — which would otherwise block in the render loop on import.
    """
    src = _FIRMWARE.read_text()
    tree = ast.parse(src)
    kept = [
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        or (isinstance(node, ast.FunctionDef) and node.name in _KEEP_FUNCS)
    ]
    module = ast.Module(body=kept, type_ignores=[])
    ast.fix_missing_locations(module)
    code = compile(module, str(_FIRMWARE), "exec")

    import ujson

    from oled_canvas import BouncingText, OledCanvas

    ns: dict = {
        "time": fake_time,
        "status": fake_status,
        "ujson": ujson,
        # main.py's imports are stripped by the AST filter, so seed the real
        # layout classes render() composes and a placeholder for the SSD1306
        # annotation (evaluated at def time).
        "OledCanvas": OledCanvas,
        "BouncingText": BouncingText,
        "SSD1306": object,
    }
    exec(code, ns)
    return ns


@pytest.fixture
def fake_time():
    """A deterministic `time` whose clock advances only on sleep_ms()."""
    return _FakeTime()


@pytest.fixture
def fake_status():
    """A `status` stand-in recording transitions in `.calls`."""
    return _FakeStatus()


@pytest.fixture
def main_ns(fake_time, fake_status):
    """Fresh AST-loaded main.py namespace with fakes injected.

    Returns a SimpleNamespace with:
      - .ns: dict of module-level names (pull render, init_display, emit, ...)
      - .time: the _FakeTime instance used as the `time` module
      - .status: the _FakeStatus instance; inspect .status.calls for transitions
    """
    ns = _load_main_namespace(fake_time, fake_status)
    return SimpleNamespace(ns=ns, time=fake_time, status=fake_status)
