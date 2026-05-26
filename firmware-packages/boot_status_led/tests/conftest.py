"""Host CPython pytest fixtures for boot_status_led.

`chip` swaps os.uname so the dispatcher picks each backend in turn.
`_reset_stubs` clears recorded pin/NeoPixel state and the
`boot_status_led.*` import cache between tests so chip-dispatch reruns
from a clean slate.
"""

import os
import sys

import machine
import neopixel
import pytest


@pytest.fixture
def chip(request, monkeypatch):
    """Set os.uname().machine to `request.param` while the test runs."""

    class _Uname:
        machine = request.param

    monkeypatch.setattr(os, "uname", lambda: _Uname())
    return request.param


@pytest.fixture(autouse=True)
def _reset_stubs():
    """Clear shared stub state and cached imports each test."""
    machine.reset()
    neopixel.reset()
    for mod in list(sys.modules):
        if mod.startswith("boot_status_led"):
            del sys.modules[mod]
    yield
