"""Host tests for writing one board's credentials into the compiled image."""

from pathlib import Path

import pytest

from matter_tools import build, provision

_BOARD = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize(
    ("port", "before", "after"),
    [
        ("/dev/ttyACM0", "default_reset", "watchdog_reset"),
        ("socket://host:5555", "no_reset", "no_reset"),
        ("rfc2217://host:5555", "no_reset", "no_reset"),
    ],
)
def test_esptool_resets_only_local_boards(port: str, before: str, after: str):
    """A locally attached board is reset around flashing; one reached over the network isn't.

    Args:
        port: The serial port or network URL flashed.
        before: The reset mode esptool uses before flashing.
        after: The reset mode esptool uses after flashing.
    """
    flash = provision.flash_command(port, Path("image.bin"))

    assert flash[flash.index("--before") + 1] == before
    assert flash[flash.index("--after") + 1] == after
    assert flash[-4:] == ["write_flash", "-z", "0x0", "image.bin"]


def test_provisioning_replaces_only_the_factory_partition():
    """Provisioning overwrites the factory partition and leaves every other byte alone."""
    identity = build.board_to_identity(_BOARD, build.DISCOVERY_MODE)
    start, size = identity.factory_offset, identity.factory_size
    image = bytes(index % 251 for index in range(identity.flash_size))

    provisioned = provision.provision_image(image, b"\xaa" * size, identity)

    assert provisioned[:start] == image[:start]
    assert provisioned[start : start + size] == b"\xaa" * size
    assert provisioned[start + size :] == image[start + size :]
