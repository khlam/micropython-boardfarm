"""Host CPython tests for init_display()'s scan/retry state machine.

init_display() references the module-global `i2c` bus and the `SSD1306` class,
both stripped by the AST loader. We inject scripted stand-ins into the loaded
namespace (functions resolve globals at call time, so post-load assignment
works) to drive the no-device and init-error retry branches to a clean return.
"""

import io
import json
from contextlib import redirect_stdout


def test_retries_until_panel_appears(main_ns):
    bus = _ScriptBus(scan_results=[[], [0x3C]])  # absent, then present
    records, oled = _run_init(main_ns, bus, _OkOled)

    assert oled.addr == 0x3C
    assert main_ns.status.calls == ["i2c_init", "no_device"]
    assert [r.get("diag") for r in records] == ["scan", "no_device", "scan", "oled_ok"]


def test_retries_until_driver_init_succeeds(main_ns):
    bus = _ScriptBus(scan_results=[[0x3C], [0x3C]])  # present both times
    records, oled = _run_init(main_ns, bus, _RaiseOnceOled)

    assert oled.addr == 0x3C
    assert main_ns.status.calls == ["i2c_init", "init_err"]
    assert "init_err" in [r.get("diag") for r in records]


def test_finds_alternate_address(main_ns):
    bus = _ScriptBus(scan_results=[[0x20, 0x3D]])  # OLED strapped to 0x3D
    _, oled = _run_init(main_ns, bus, _OkOled)
    assert oled.addr == 0x3D


def _run_init(main_ns, bus, oled_cls):
    """Inject the bus + driver class and run init_display() to its return."""
    main_ns.ns["i2c"] = bus
    main_ns.ns["SSD1306"] = oled_cls
    init_display = main_ns.ns["init_display"]
    buf = io.StringIO()
    with redirect_stdout(buf):
        oled = init_display()
    records = [json.loads(line) for line in buf.getvalue().splitlines() if line.strip()]
    return records, oled


class _ScriptBus:
    """I²C bus stand-in returning successive scripted scan results."""

    def __init__(self, scan_results) -> None:
        self._scan_results = list(scan_results)

    def scan(self) -> list[int]:
        return self._scan_results.pop(0)


class _OkOled:
    """SSD1306 stand-in whose construction always succeeds."""

    def __init__(self, _i2c, _width, _height, addr) -> None:
        self.addr = addr


class _RaiseOnceOled:
    """SSD1306 stand-in that raises OSError on its first construction only."""

    _attempts = 0

    def __init__(self, _i2c, _width, _height, addr) -> None:
        type(self)._attempts += 1
        if type(self)._attempts == 1:
            raise OSError("ENODEV")
        self.addr = addr
