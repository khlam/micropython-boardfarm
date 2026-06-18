"""Host CPython pytest fixtures for board_pinout.

`chip` swaps os.uname so the dispatcher picks each backend in turn.
`_reset_modules` clears cached board_pinout modules between tests so the
dispatcher re-runs its os.uname() lookup on every parametrization.
"""

import os
import sys

import pytest


@pytest.fixture
def chip(request, monkeypatch):
    """Set os.uname().machine to `request.param` while the test runs."""

    class _Uname:
        machine = request.param

    monkeypatch.setattr(os, "uname", _Uname)
    return request.param


@pytest.fixture(autouse=True)
def _reset_modules():
    """Drop cached board_pinout modules each test so import-time dispatch reruns."""
    for mod in list(sys.modules):
        if mod.startswith("board_pinout"):
            del sys.modules[mod]
    yield
