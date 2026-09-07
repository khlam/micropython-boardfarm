"""Host CPython pytest tests for _target_dict() in ld2450 firmware.

Pure function: converts one Target-shaped object into the JSON fields used
by the dashboard. No UART, no async, no BOARD dispatch involved.
"""

import os
import pathlib
from collections import namedtuple
from math import atan2, degrees, sqrt

from micropython_stubs.testing import firmware_namespace

_FIRMWARE = pathlib.Path(__file__).parent.parent / "firmware" / "main.py"
_KEEP_FUNCS = {"_target_dict"}


class _Target:
    """Minimal stand-in for ld2450.Target — the five attributes _target_dict reads."""

    def __init__(self, slot, x_mm, y_mm, speed_cm_s, resolution_mm) -> None:
        self.slot = slot
        self.x_mm = x_mm
        self.y_mm = y_mm
        self.speed_cm_s = speed_cm_s
        self.resolution_mm = resolution_mm


def _target_dict(target):
    ns = firmware_namespace(
        _FIRMWARE,
        _KEEP_FUNCS,
        os=os,
        namedtuple=namedtuple,
        sqrt=sqrt,
        atan2=atan2,
        degrees=degrees,
    )
    return ns.ns["_target_dict"](target)


def test_target_dict_has_the_documented_schema():
    result = _target_dict(_Target(1, 100, 200, 0, 50))
    assert set(result.keys()) == {
        "slot",
        "x_mm",
        "y_mm",
        "speed_cm_s",
        "resolution_mm",
        "distance_mm",
        "angle_deg",
    }


def test_target_dict_distance_is_rounded_hypotenuse():
    result = _target_dict(_Target(1, 300, 400, 0, 0))
    assert result["distance_mm"] == 500  # 3-4-5 triangle


def test_target_dict_straight_ahead_is_zero_degrees():
    result = _target_dict(_Target(1, 0, 100, 0, 0))
    assert result["angle_deg"] == 0


def test_target_dict_all_four_quadrant_signs():
    front_left = _target_dict(_Target(1, -50, 50, 0, 0))["angle_deg"]
    front_right = _target_dict(_Target(1, 50, 50, 0, 0))["angle_deg"]
    back_left = _target_dict(_Target(1, -50, -50, 0, 0))["angle_deg"]
    back_right = _target_dict(_Target(1, 50, -50, 0, 0))["angle_deg"]
    assert front_left < 0
    assert front_right > 0
    assert back_left < -90
    assert back_right > 90


def test_target_dict_origin_does_not_raise():
    result = _target_dict(_Target(1, 0, 0, 0, 0))
    assert result["distance_mm"] == 0
    assert result["angle_deg"] == 0
