"""Board provisioning, offline QR generation, and firmware/host agreement."""

import argparse
import csv
import sys
from pathlib import Path

import build
import pairing
import pairing_code
import pytest

from matter import generate_pairing

_KEY = "correct-horse-battery-staple"
_BOARD = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize(
    ("port", "before", "after"),
    [
        ("/dev/ttyACM0", "default_reset", "watchdog_reset"),
        ("socket://host:5555", "no_reset", "no_reset"),
        ("rfc2217://host:5555", "no_reset", "no_reset"),
    ],
)
def test_esptool_resets_only_local_boards(port, before, after):
    flash = build._flash_command(port, Path("image.bin"))

    assert flash[flash.index("--before") + 1] == before
    assert flash[flash.index("--after") + 1] == after
    assert flash[-4:] == ["write_flash", "-z", "0x0", "image.bin"]


def test_provisioning_replaces_only_the_factory_partition():
    identity = build.board_to_identity(_BOARD, build.DISCOVERY_MODE)
    start, size = identity.factory_offset, identity.factory_size
    image = bytes(index % 251 for index in range(identity.flash_size))

    provisioned = build._provision_image(image, b"\xaa" * size, identity)

    assert provisioned[:start] == image[:start]
    assert provisioned[start : start + size] == b"\xaa" * size
    assert provisioned[start + size :] == image[start + size :]


def test_offline_qr_matches_firmware(monkeypatch, tmp_path, capsys):
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
    decoded = build._decode_qr_payload(setup["setup_payload"])
    assert decoded["passcode"] == expected["passcode"]
    assert decoded["discriminator"] == expected["discriminator"]
    assert decoded["vendor_id"] == 0xFFF1
    assert decoded["product_id"] == 0x8001
    assert setup["manual_pairing_code"] == expected["manual_pairing_code"]
    assert build._decode_manual_code(setup["manual_pairing_code"]) == {
        "passcode": expected["passcode"],
        "short_discriminator": expected["discriminator"] >> 8,
    }
    assert output.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


def test_compilation_is_board_free_and_removes_stale_codes(pipeline, monkeypatch):
    identity, _args, outputs, calls = pipeline
    monkeypatch.setattr(sys, "argv", ["build.py"])
    monkeypatch.setattr(build, "BOARD_DIR", _BOARD)
    monkeypatch.setattr(build, "_BUILD_CACHE", outputs.parent / "cache")
    monkeypatch.setattr(build, "_OWNER_REFERENCE", outputs)
    monkeypatch.setattr(build, "_build_firmware", lambda *_args: None)

    def merge(_cache, _identity, *, artifact_root):
        path = artifact_root / build._MERGED_NAME
        path.write_bytes(b"\xff" * identity.flash_size)
        return path

    def unexpected(*_args):
        pytest.fail("compilation tried to generate board credentials")

    monkeypatch.setattr(build, "_merge_image", merge)
    monkeypatch.setattr(build, "_mint_credentials", unexpected)
    assert build.main() == 0
    assert {path.name for path in outputs.iterdir()} == {build._MERGED_NAME}
    assert not calls


def test_explicit_passcode_reproduces_pairing_codes(pipeline, tmp_path, monkeypatch):
    identity, args, outputs, calls = pipeline
    args.passcode = _KEY

    def unexpected():
        pytest.fail("an explicit passcode drew a random one")

    monkeypatch.setattr(pairing, "_random_passcode", unexpected)
    flashes = []
    for index in range(2):
        build._flash_board(tmp_path / str(index), identity, args)
        flashes.append(_published_pairing(outputs))
    assert flashes[0] == flashes[1]
    setup, qr = flashes[0]
    expected = generate_pairing(_KEY)
    assert setup["passcode"] == _KEY
    assert setup["manual_pairing_code"] == expected["manual_pairing_code"]
    assert build._decode_qr_payload(setup["setup_payload"])["passcode"] == expected["passcode"]
    assert qr.startswith(b"\x89PNG\r\n\x1a\n")
    _command, image = calls[-1]
    assert (outputs / build._MERGED_NAME).read_bytes() == image
    assert image[: identity.factory_offset] == b"\xff" * identity.factory_offset


def test_blank_passcode_produces_random_pairing_codes(pipeline, tmp_path, monkeypatch):
    identity, args, outputs, _calls = pipeline
    draw_passcode = pairing._random_passcode
    draws = []

    def counted_draw():
        draws.append(draw_passcode())
        return draws[-1]

    monkeypatch.setattr(pairing, "_random_passcode", counted_draw)
    setups = []
    for index in range(2):
        build._flash_board(tmp_path / str(index), identity, args)
        setups.append(_published_pairing(outputs)[0])
    assert len(draws) == 2
    # Two independent 256-bit keys share a pairing code with negligible probability.
    for field in ("passcode", "manual_pairing_code", "setup_payload"):
        assert setups[0][field] != setups[1][field]


def test_flash_refuses_a_wrong_size_image(pipeline, tmp_path):
    identity, args, outputs, calls = pipeline
    (outputs / build._MERGED_NAME).write_bytes(b"invalid")

    with pytest.raises(ValueError, match="merged image must be exactly"):
        build._flash_board(tmp_path, identity, args)
    assert not calls


def test_failed_flash_preserves_published_artifacts(pipeline, tmp_path, monkeypatch):
    identity, args, outputs, _calls = pipeline
    before = {path.name: path.read_bytes() for path in outputs.iterdir()}

    def fail(*_args):
        raise OSError("serial failure")

    monkeypatch.setattr(build, "_run", fail)
    with pytest.raises(OSError, match="serial failure"):
        build._flash_board(tmp_path, identity, args)
    assert {path.name: path.read_bytes() for path in outputs.iterdir()} == before


@pytest.fixture
def pipeline(tmp_path, monkeypatch):
    identity = build.board_to_identity(_BOARD, build.DISCOVERY_MODE)
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    (outputs / build._MERGED_NAME).write_bytes(b"\xff" * identity.flash_size)
    (outputs / build._QR_NAME).write_bytes(b"previous QR")
    (outputs / build._SETUP_NAME).write_text("previous setup")
    metadata = tmp_path / "pyproject.toml"
    metadata.write_text('[project]\nname = "Test board"\n')
    monkeypatch.setattr(build, "_OUTPUT_DIR", outputs)
    monkeypatch.setattr(build, "_PROJECT_TOML", metadata)

    def read_factory(path, _namespace):
        with path.with_suffix(".csv").open() as stream:
            return {
                row["key"]: int(row["value"]) if row["encoding"] == "u32" else row["value"]
                for row in csv.DictReader(stream)
            }

    monkeypatch.setattr(build.nvs_partition_read, "read_factory_partition", read_factory)
    calls = []
    monkeypatch.setattr(
        build, "_run", lambda command: calls.append((command, Path(command[-1]).read_bytes()))
    )
    args = argparse.Namespace(port="/dev/ttyACM0", passcode="", manufacturer="", serial_number="")
    return identity, args, outputs, calls


def _published_pairing(outputs):
    """Return the published setup fields and QR bytes from the latest flash."""
    setup = dict(
        line.split("=", 1) for line in (outputs / build._SETUP_NAME).read_text().splitlines()
    )
    return setup, (outputs / build._QR_NAME).read_bytes()
