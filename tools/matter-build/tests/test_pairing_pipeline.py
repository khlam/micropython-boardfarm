"""Board provisioning, offline QR generation, and firmware/host agreement."""

import argparse
import csv
import sys
from pathlib import Path

import build
import pairing_code
import provision
import pytest

from matter_tools import _nvs_partition_read, _pairing
from matter_tools.build import (
    MERGED_NAME,
    QR_NAME,
    SETUP_NAME,
    BoardIdentity,
    board_to_identity,
)
from matter_tools.provision import _decode_qr_payload, generate_pairing

_KEY = "correct-horse-battery-staple"
# The package's own board fixture, reached through the pytest container's mount.
_BOARD = Path("/cpython-packages/matter_tools/tests/fixtures")

# The board identity, flash arguments, outputs directory, and every recorded
# esptool run with the image it wrote.
_Pipeline = tuple[BoardIdentity, argparse.Namespace, Path, list[tuple[list[str], bytes]]]


def test_offline_qr_matches_firmware(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    """The offline pairing tool derives the same codes from a key as the firmware does.

    Args:
        monkeypatch: Sets the tool's command line.
        tmp_path: Receives the QR image.
        capsys: Captures the setup fields the tool prints.
    """
    output = tmp_path / "pairing.png"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "pairing_code.py",
            "--passcode",
            _KEY,
            "--board-dir",
            str(_BOARD),
            "--output",
            str(output),
        ],
    )
    pairing_code.main()
    setup = dict(line.split("=", 1) for line in capsys.readouterr().out.splitlines())
    expected = generate_pairing(_KEY)
    decoded = _decode_qr_payload(setup["setup_payload"])
    assert decoded["passcode"] == expected["passcode"]
    assert decoded["discriminator"] == expected["discriminator"]
    assert decoded["vendor_id"] == 0xFFF1
    assert decoded["product_id"] == 0x8001
    assert setup["manual_pairing_code"] == expected["manual_pairing_code"]
    assert output.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


def test_provision_cli_flashes_the_named_port_with_the_given_key(
    pipeline: _Pipeline, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """The provisioning caller writes to the named port and publishes codes for the given key.

    Args:
        pipeline: The prepared outputs and recorded esptool runs.
        monkeypatch: Sets the command line and the board and output locations.
        capsys: Captures the completion message.
    """
    _identity, _args, outputs, calls = pipeline
    port = "socket://host:5555"
    monkeypatch.setattr(sys, "argv", ["provision.py", "--port", port, "--passcode", _KEY])
    monkeypatch.setattr(build, "BOARD_DIR", _BOARD)
    monkeypatch.setattr(build, "OWNER_REFERENCE", outputs)

    assert provision.main() == 0
    assert capsys.readouterr().out.splitlines()[-1] == "Matter flash complete"
    ((command, _image),) = calls
    assert command[command.index("--port") + 1] == port
    assert _published_pairing(outputs)[0]["passcode"] == _KEY


def test_compilation_is_board_free_and_removes_stale_codes(
    pipeline: _Pipeline, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """Compiling flashes nothing and leaves only the merged image.

    Args:
        pipeline: The prepared outputs and recorded esptool runs.
        monkeypatch: Stubs out the firmware build and points it at the board and cache.
        capsys: Captures the completion message.
    """
    identity, _args, outputs, calls = pipeline
    monkeypatch.setattr(build, "BOARD_DIR", _BOARD)
    monkeypatch.setattr(build, "_BUILD_CACHE", outputs.parent / "cache")
    monkeypatch.setattr(build, "OWNER_REFERENCE", outputs)
    monkeypatch.setattr(build, "build_firmware", lambda *_args, **_kwargs: None)

    def merge(_cache, _identity, *, artifact_root):
        path = artifact_root / MERGED_NAME
        path.write_bytes(b"\xff" * identity.flash_size)
        return path

    monkeypatch.setattr(build, "merge_image", merge)
    assert build.main() == 0
    assert capsys.readouterr().out.splitlines()[-1] == "Matter firmware ready to provision"
    assert {path.name for path in outputs.iterdir()} == {MERGED_NAME}
    assert not calls


def test_explicit_passcode_reproduces_pairing_codes(
    pipeline: _Pipeline, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Flashing twice with the same key publishes the same codes and writes the merged image.

    Args:
        pipeline: The prepared outputs and recorded esptool runs.
        tmp_path: Holds each flash's working directory.
        monkeypatch: Fails the test if a random passcode is drawn.
    """
    identity, args, outputs, calls = pipeline
    args.passcode = _KEY

    def unexpected():
        pytest.fail("an explicit passcode drew a random one")

    monkeypatch.setattr(_pairing, "_random_passcode", unexpected)
    flashes = []
    for index in range(2):
        provision._provision_board(tmp_path / str(index), identity, args)
        flashes.append(_published_pairing(outputs))
    assert flashes[0] == flashes[1]
    setup, qr = flashes[0]
    expected = generate_pairing(_KEY)
    assert setup["passcode"] == _KEY
    assert setup["manual_pairing_code"] == expected["manual_pairing_code"]
    assert _decode_qr_payload(setup["setup_payload"])["passcode"] == expected["passcode"]
    assert qr.startswith(b"\x89PNG\r\n\x1a\n")
    _command, image = calls[-1]
    assert (outputs / MERGED_NAME).read_bytes() == image
    assert image[: identity.factory_offset] == b"\xff" * identity.factory_offset


def test_blank_passcode_produces_random_pairing_codes(
    pipeline: _Pipeline, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Each flash without a key draws a fresh random one and publishes different codes.

    Args:
        pipeline: The prepared outputs and recorded esptool runs.
        tmp_path: Holds each flash's working directory.
        monkeypatch: Counts the random passcode draws.
    """
    identity, args, outputs, _calls = pipeline
    draw_passcode = _pairing._random_passcode
    draws = []

    def counted_draw():
        draws.append(draw_passcode())
        return draws[-1]

    monkeypatch.setattr(_pairing, "_random_passcode", counted_draw)
    setups = []
    for index in range(2):
        provision._provision_board(tmp_path / str(index), identity, args)
        setups.append(_published_pairing(outputs)[0])
    assert len(draws) == 2
    # Two independent 256-bit keys share a pairing code with negligible probability.
    for field in ("passcode", "manual_pairing_code", "setup_payload"):
        assert setups[0][field] != setups[1][field]


def test_flash_refuses_a_wrong_size_image(pipeline: _Pipeline, tmp_path: Path):
    """A merged image that isn't exactly the flash size is refused before esptool runs.

    Args:
        pipeline: The prepared outputs and recorded esptool runs.
        tmp_path: The flash's working directory.
    """
    identity, args, outputs, calls = pipeline
    (outputs / MERGED_NAME).write_bytes(b"invalid")

    with pytest.raises(ValueError, match="merged image must be exactly"):
        provision._provision_board(tmp_path, identity, args)
    assert not calls


def test_failed_flash_preserves_published_artifacts(
    pipeline: _Pipeline, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A flash that fails leaves the previously published outputs untouched.

    Args:
        pipeline: The prepared outputs and recorded esptool runs.
        tmp_path: The flash's working directory.
        monkeypatch: Makes esptool fail.
    """
    identity, args, outputs, _calls = pipeline
    before = {path.name: path.read_bytes() for path in outputs.iterdir()}

    def fail(*_args):
        raise OSError("serial failure")

    monkeypatch.setattr(provision, "run", fail)
    with pytest.raises(OSError, match="serial failure"):
        provision._provision_board(tmp_path, identity, args)
    assert {path.name: path.read_bytes() for path in outputs.iterdir()} == before


@pytest.fixture
def pipeline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> _Pipeline:
    """An outputs directory holding a blank merged image and stale pairing codes.

    Args:
        tmp_path: Holds the outputs directory and project metadata.
        monkeypatch: Points the callers at them, reads factory data from its CSV,
            and records esptool runs instead of flashing.

    Returns:
        The board identity, flash arguments, outputs directory, and recorded runs.
    """
    identity = board_to_identity(_BOARD)
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    (outputs / MERGED_NAME).write_bytes(b"\xff" * identity.flash_size)
    (outputs / QR_NAME).write_bytes(b"previous QR")
    (outputs / SETUP_NAME).write_text("previous setup")
    metadata = tmp_path / "pyproject.toml"
    metadata.write_text('[project]\nname = "Test board"\n')
    monkeypatch.setattr(build, "OUTPUT_DIR", outputs)
    monkeypatch.setattr(build, "PROJECT_TOML", metadata)

    def read_factory(path, _namespace):
        with path.with_suffix(".csv").open() as stream:
            return {
                row["key"]: int(row["value"]) if row["encoding"] == "u32" else row["value"]
                for row in csv.DictReader(stream)
            }

    monkeypatch.setattr(_nvs_partition_read, "read_factory_partition", read_factory)
    calls = []
    monkeypatch.setattr(
        provision, "run", lambda command: calls.append((command, Path(command[-1]).read_bytes()))
    )
    args = argparse.Namespace(port="/dev/ttyACM0", passcode="", manufacturer="", serial_number="")
    return identity, args, outputs, calls


def _published_pairing(outputs: Path) -> tuple[dict[str, str], bytes]:
    """Return the published setup fields and QR bytes from the latest flash.

    Args:
        outputs: The outputs directory.

    Returns:
        The setup fields, keyed by name, and the QR image.
    """
    setup = dict(line.split("=", 1) for line in (outputs / SETUP_NAME).read_text().splitlines())
    return setup, (outputs / QR_NAME).read_bytes()
