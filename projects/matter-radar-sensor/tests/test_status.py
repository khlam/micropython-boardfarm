"""Status pixel priority and commissioning-session tracking."""

from collections.abc import Callable
from types import ModuleType, SimpleNamespace

import neopixel
import pytest

from matter import Commissioning


@pytest.mark.parametrize(
    ("commissioning", "session_active", "commissioned", "healthy", "occupied", "color"),
    [
        (Commissioning.FAILED, True, True, False, True, "_COMMISSIONING_FAILED_COLOR"),
        (Commissioning.OPENED, False, True, False, True, "_COMMISSIONING_WINDOW_COLOR"),
        (Commissioning.CLOSED, True, False, True, True, "_COMMISSIONING_SESSION_COLOR"),
        (Commissioning.CLOSED, False, False, True, True, "_COMMISSIONING_STOPPED_COLOR"),
        (None, False, False, False, False, "_BOOT_COLOR"),
        (Commissioning.CLOSED, False, True, False, True, "_RADAR_FAILED_COLOR"),
        (Commissioning.CLOSED, False, True, True, True, "_OCCUPIED_COLOR"),
        (None, False, True, True, False, "_VACANT_COLOR"),
    ],
)
def test_status_color_priority(
    status: ModuleType,
    commissioning: str | None,
    session_active: bool,
    commissioned: bool,
    healthy: bool,
    occupied: bool,
    color: str,
):
    """Each row's highest-priority condition decides the pixel color.

    Args:
        status: The firmware status module.
        commissioning: The last commissioning state, or None before any event.
        session_active: Whether a commissioning session is in progress.
        commissioned: Whether the node holds a fabric.
        healthy: Whether the radar is reporting.
        occupied: Whether the room reads as occupied.
        color: Name of the status module constant expected.
    """
    assert status.status_color(
        commissioning=commissioning,
        session_active=session_active,
        commissioned=commissioned,
        healthy=healthy,
        occupied=occupied,
    ) == getattr(status, color)


@pytest.mark.parametrize(
    "timeline",
    [
        pytest.param(
            [
                (Commissioning.OPENED, "_COMMISSIONING_WINDOW_COLOR"),
                (Commissioning.STARTED, "_COMMISSIONING_SESSION_COLOR"),
                (Commissioning.CLOSED, "_COMMISSIONING_SESSION_COLOR"),
                (Commissioning.COMPLETE, "_OCCUPIED_COLOR"),
            ],
            id="session-stays-active-through-a-closed-window-until-completion",
        ),
        pytest.param(
            [
                (Commissioning.STARTED, "_COMMISSIONING_SESSION_COLOR"),
                (Commissioning.FAILED, "_COMMISSIONING_FAILED_COLOR"),
                (Commissioning.OPENED, "_COMMISSIONING_WINDOW_COLOR"),
                (Commissioning.CLOSED, "_COMMISSIONING_STOPPED_COLOR"),
            ],
            id="failure-ends-the-session-and-shows-until-the-next-event",
        ),
    ],
)
def test_commissioning_events_drive_the_pixel(status: ModuleType, timeline: list[tuple[str, str]]):
    """Each commissioning event of an unpaired node leaves the pixel its color.

    Args:
        status: The firmware status module.
        timeline: Each event's state, paired with the color constant it leaves.
    """
    status_pixel, pixel = _pixel(status)

    colors = []
    for state, _color in timeline:
        status_pixel.on_commissioning(_event(state))
        colors.append(pixel.writes[-1])

    assert colors == [getattr(status, color) for _state, color in timeline]


def test_pixel_is_written_only_when_its_color_changes(status: ModuleType):
    """A product update that leaves the color unchanged doesn't rewrite the pixel.

    Args:
        status: The firmware status module.
    """
    status_pixel, pixel = _pixel(status)
    status_pixel.set_commissioned(value=True)

    status_pixel.update_product(occupied=True, healthy=True)
    status_pixel.update_product(occupied=True, healthy=True)

    assert pixel.writes == [status._BOOT_COLOR, status._OCCUPIED_COLOR]


@pytest.fixture
def status(firmware_module: Callable[[str], ModuleType]) -> ModuleType:
    """The firmware status module, imported fresh.

    Args:
        firmware_module: Imports the module from the firmware directory.

    Returns:
        The status module.
    """
    return firmware_module("status")


def _pixel(status):
    pixel = neopixel.NeoPixel(None, 1)
    return status.StatusPixel(pixel), pixel


def _event(state):
    return SimpleNamespace(state=state)
