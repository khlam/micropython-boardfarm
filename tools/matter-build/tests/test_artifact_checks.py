"""Host tests for build.py's image-shape checks and its /outputs publishing step.

A merged image is a few megabytes of flash layout, so the fixtures here build a
miniature one: the identity's flash size and factory offset are shrunk to a few
hundred bytes, which exercises exactly the same slice arithmetic.
"""

import pathlib

import build
import pytest

_FLASH_SIZE = 512
_FACTORY_OFFSET = 128
_FACTORY_SIZE = 64


def test_accepts_an_image_carrying_its_factory_partition(image, identity):
    build._validate_merged_image(image.merged, image.factory, image.qr, identity)


def test_rejects_an_empty_image(image, identity):
    image.merged.write_bytes(b"")
    with pytest.raises(ValueError, match=r"exceeds the .* byte flash layout"):
        build._validate_merged_image(image.merged, image.factory, image.qr, identity)


def test_rejects_an_image_larger_than_the_flash(image, identity):
    image.merged.write_bytes(b"\x00" * (_FLASH_SIZE + 1))
    with pytest.raises(ValueError, match=r"exceeds the .* byte flash layout"):
        build._validate_merged_image(image.merged, image.factory, image.qr, identity)


def test_rejects_a_factory_partition_of_the_wrong_size(image, identity):
    image.factory.write_bytes(b"\xaa" * (_FACTORY_SIZE - 1))
    with pytest.raises(ValueError, match="must be exactly"):
        build._validate_merged_image(image.merged, image.factory, image.qr, identity)


def test_rejects_an_image_missing_the_factory_partition(image, identity):
    # The image is intact and correctly sized, but was merged with other credentials.
    merged = bytearray(image.merged.read_bytes())
    merged[_FACTORY_OFFSET] ^= 0xFF
    image.merged.write_bytes(bytes(merged))
    with pytest.raises(ValueError, match="does not carry the generated factory partition"):
        build._validate_merged_image(image.merged, image.factory, image.qr, identity)


def test_rejects_a_missing_qr_image(image, identity):
    image.qr.unlink()
    with pytest.raises(ValueError, match="QR image is missing or empty"):
        build._validate_merged_image(image.merged, image.factory, image.qr, identity)


def test_rejects_an_empty_qr_image(image, identity):
    image.qr.write_bytes(b"")
    with pytest.raises(ValueError, match="QR image is missing or empty"):
        build._validate_merged_image(image.merged, image.factory, image.qr, identity)


def test_publish_installs_both_artifacts_readable(image, outputs):
    published = build._publish(image.merged, image.qr)

    assert published == outputs / build._MERGED_NAME
    assert published.read_bytes() == image.merged.read_bytes()
    assert (outputs / build._QR_NAME).read_bytes() == image.qr.read_bytes()
    assert published.stat().st_mode & 0o777 == build._ARTIFACT_MODE


def test_publish_drops_a_stale_setup_file(image, outputs):
    # Its pairing code belongs to the previous build's image, so it must not
    # survive into a run that has not yet written its own.
    (outputs / build._SETUP_NAME).write_text("manual_pairing_code=stale\n", encoding="utf-8")
    build._publish(image.merged, image.qr)
    assert not (outputs / build._SETUP_NAME).exists()


def test_publish_refuses_to_write_beside_a_stray_file(image, outputs):
    (outputs / "leftover.bin").write_bytes(b"")
    with pytest.raises(ValueError, match=r"unexpected output artifacts: leftover\.bin"):
        build._publish(image.merged, image.qr)
    assert not (outputs / build._MERGED_NAME).exists()


def test_write_setup_names_both_codes(outputs):
    build._write_setup("34970112332", "MT:-24J0AFN00KA0648G00")

    setup = outputs / build._SETUP_NAME
    assert setup.read_text(encoding="utf-8") == (
        "manual_pairing_code=34970112332\nsetup_payload=MT:-24J0AFN00KA0648G00\n"
    )
    assert setup.stat().st_mode & 0o777 == build._ARTIFACT_MODE


class _Image:
    """The three files a finished build hands to the artifact checks."""

    def __init__(self, root: pathlib.Path) -> None:
        """Write a merged image carrying its factory partition at the right offset."""
        factory_bytes = bytes(range(256))[:_FACTORY_SIZE]
        merged = bytearray(b"\x00" * _FLASH_SIZE)
        merged[_FACTORY_OFFSET : _FACTORY_OFFSET + _FACTORY_SIZE] = factory_bytes

        self.merged = root / build._MERGED_NAME
        self.factory = root / "factory-partition.bin"
        self.qr = root / "device-qrcode.png"
        self.merged.write_bytes(bytes(merged))
        self.factory.write_bytes(factory_bytes)
        self.qr.write_bytes(b"\x89PNG\r\n\x1a\n")


@pytest.fixture
def identity():
    """A build identity shrunk to the miniature image the fixtures build."""
    return build._BuildIdentity(
        vendor_id=0xFFF1,
        product_id=0x8001,
        factory_offset=_FACTORY_OFFSET,
        factory_size=_FACTORY_SIZE,
        flash_size=_FLASH_SIZE,
        discovery_mode=2,
    )


@pytest.fixture
def image(tmp_path):
    """A consistent merged image, factory partition and QR file under tmp_path."""
    source = tmp_path / "build"
    source.mkdir()
    return _Image(source)


@pytest.fixture
def outputs(tmp_path, monkeypatch):
    """Redirect the module's /outputs bind mount at an empty directory."""
    directory = tmp_path / "outputs"
    directory.mkdir()
    monkeypatch.setattr(build, "_OUTPUT_DIR", directory)
    return directory
