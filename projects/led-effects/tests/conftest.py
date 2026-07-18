import pathlib
import sys

import machine
import neopixel
import pytest

_FIRMWARE_DIR = str(pathlib.Path(__file__).parent.parent / "firmware")
if _FIRMWARE_DIR not in sys.path:
    sys.path.insert(0, _FIRMWARE_DIR)


@pytest.fixture(autouse=True)
def _reset_stubs():
    machine.reset()
    neopixel.reset()
    yield
