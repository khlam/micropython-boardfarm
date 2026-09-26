"""Status pixel priority and commissioning-session tracking."""

from types import SimpleNamespace

import neopixel
import pytest

import matter

_C = matter.Commissioning


@pytest.fixture
def status(firmware_module):
    return firmware_module("status")


@pytest.mark.parametrize(
    ("commissioning", "session_active", "commissioned", "healthy", "occupied", "color"),
    [
        (_C.FAILED, True, True, False, True, "_COMMISSIONING_FAILED_COLOR"),
        (_C.OPENED, False, True, False, True, "_COMMISSIONING_WINDOW_COLOR"),
        (_C.CLOSED, True, False, True, True, "_COMMISSIONING_SESSION_COLOR"),
        (_C.CLOSED, False, False, True, True, "_COMMISSIONING_STOPPED_COLOR"),
        (None, False, False, False, False, "_BOOT_COLOR"),
        (_C.CLOSED, False, True, False, True, "_RADAR_FAILED_COLOR"),
        (_C.CLOSED, False, True, True, True, "_OCCUPIED_COLOR"),
        (None, False, True, True, False, "_VACANT_COLOR"),
    ],
)
def test_status_color_priority(
    status, commissioning, session_active, commissioned, healthy, occupied, color
):
    assert status.status_color(
        commissioning=commissioning,
        session_active=session_active,
        commissioned=commissioned,
        healthy=healthy,
        occupied=occupied,
    ) == getattr(status, color)


def _pixel(status):
    pixel = neopixel.NeoPixel(None, 1)
    return status.StatusPixel(pixel), pixel


def _event(state):
    return SimpleNamespace(state=state)


def test_session_stays_active_through_a_closed_window_until_completion(status):
    status_pixel, pixel = _pixel(status)

    for state in (_C.OPENED, _C.STARTED, _C.CLOSED, _C.COMPLETE):
        status_pixel.on_commissioning(_event(state))

    assert pixel.writes == [
        status._BOOT_COLOR,
        status._COMMISSIONING_WINDOW_COLOR,
        status._COMMISSIONING_SESSION_COLOR,
        status._OCCUPIED_COLOR,
    ]


def test_failure_ends_the_session_and_shows_until_the_next_event(status):
    status_pixel, pixel = _pixel(status)

    for state in (_C.STARTED, _C.FAILED, _C.OPENED):
        status_pixel.on_commissioning(_event(state))

    assert pixel.writes[-2:] == [
        status._COMMISSIONING_FAILED_COLOR,
        status._COMMISSIONING_WINDOW_COLOR,
    ]
    assert status_pixel._commissioning_session_active is False


def test_pixel_is_written_only_when_its_color_changes(status):
    status_pixel, pixel = _pixel(status)
    status_pixel.set_commissioned(value=True)

    status_pixel.update_product(occupied=True, healthy=True)
    status_pixel.update_product(occupied=True, healthy=True)

    assert pixel.writes == [status._BOOT_COLOR, status._OCCUPIED_COLOR]
